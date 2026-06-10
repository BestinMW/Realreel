import base64
import json
import os
import re
from copy import deepcopy
from pathlib import Path

import httpx

from .config import (
    GEMINI_MODEL,
    GEMINI_TIMEOUT_MS,
    VERTEX_AI_GEMINI_MODEL,
    VERTEX_AI_LOCATION,
    VERTEX_AI_PROJECT_ID,
    VISION_ENABLED,
    VISION_PROVIDER,
)
from .indicators import (
    DEFAULT_VISION_INDICATORS,
    GEMINI_RESPONSE_SCHEMA,
    VISION_PROMPT,
    normalize_vision_indicators,
)

AUTHENTICITY_PROMPT = """Assess whether this single video frame appears to be authentic camera footage or synthetic/manipulated imagery.
Focus on observable visual evidence only. Do not rely on whether the event is plausible in the real world.
Check physics, lighting, shadows, reflections, perspective, scale, object continuity, texture consistency, smoke/fire/water/debris behavior, malformed details, warped geometry, repeated patterns, and other signs of generated or edited video.
Return valid JSON only:
{
  "authenticityRisk": 0.0,
  "riskLevel": "low|medium|high",
  "rationale": "short explanation",
  "riskSignals": ["specific observable signals that increase synthetic/manipulation risk"],
  "realismSignals": ["specific observable signals that support authentic camera footage"],
  "signals": ["legacy combined list; duplicate riskSignals here if needed"]
}"""

EVENT_WINDOW_CONSISTENCY_PROMPT = """Assess whether a short before/during/after video event window is physically and temporally consistent.
You will receive JSON frame metadata in timestamp order. Focus on cross-frame behavior, not whether each frame looks realistic alone.
Check subject reaction, lighting changes, shadows/reflections, debris/smoke/fire continuity, camera motion, object persistence, scale, and whether nearby people/objects physically interact with the event.
Return valid JSON only:
{
  "physicalConsistencyRisk": 0.0,
  "subjectReactionRisk": 0.0,
  "lightingContinuityRisk": 0.0,
  "debrisMotionRisk": 0.0,
  "cameraContinuityRisk": 0.0,
  "overallTemporalAuthenticityRisk": 0.0,
  "rationale": "short explanation",
  "riskSignals": ["specific cross-frame inconsistencies"],
  "consistencySignals": ["specific signals that support authentic continuity"]
}"""


def empty_vision_result(error: str | None = None) -> dict:
    return {
        "ok": error is None,
        "indicators": deepcopy(DEFAULT_VISION_INDICATORS),
        "error": error,
    }


def build_vision_prompt(ocr_summary: str | None) -> str:
    if not ocr_summary:
        return VISION_PROMPT
    return (
        f"{VISION_PROMPT}\n\n"
        "OCR preprocessing summary from Tesseract. Use this as context, but still "
        f"read visible text yourself when possible: {ocr_summary}"
    )


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _repair_json_text(text: str) -> str:
    repaired = text
    repaired = repaired.replace(": boolean", ": false")
    repaired = repaired.replace(": string", ':""')
    repaired = re.sub(r",\s*}", "}", repaired)
    repaired = re.sub(r",\s*]", "]", repaired)
    return repaired


def parse_json_response(text: str) -> dict | None:
    if not text or not text.strip():
        return None

    candidates = [
        text.strip(),
        _strip_code_fence(text),
        _repair_json_text(_strip_code_fence(text)),
    ]

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    fenced = _strip_code_fence(text)
    for match in re.finditer(r"\{[\s\S]*?\}", fenced):
        snippet = _repair_json_text(match.group(0))
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict) and "medium" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue

    match = re.search(r"\{[\s\S]*\}", fenced)
    if match:
        try:
            parsed = json.loads(_repair_json_text(match.group(0)))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None

    return None


def extract_gemini_text(payload: dict) -> tuple[str | None, str | None]:
    prompt_feedback = payload.get("promptFeedback") or {}
    block_reason = prompt_feedback.get("blockReason")
    if block_reason:
        return None, f"Gemini blocked the request: {block_reason}"

    candidates = payload.get("candidates") or []
    if not candidates:
        return None, "Gemini returned no candidates."

    candidate = candidates[0]
    finish_reason = candidate.get("finishReason")
    if finish_reason and finish_reason not in {"STOP", "MAX_TOKENS"}:
        return None, f"Gemini finish reason: {finish_reason}"

    parts = candidate.get("content", {}).get("parts") or []
    text_parts = [part.get("text", "") for part in parts if part.get("text")]
    if not text_parts:
        return None, "Gemini returned empty text."

    return "".join(text_parts), None


def analyze_frame_with_gemini(frame_path: Path, *, ocr_summary: str | None = None) -> dict:
    if not VISION_ENABLED:
        return empty_vision_result("Gemini vision disabled by ENABLE_KEYFRAME_VISION=false.")
    if VISION_PROVIDER == "vertex_ai":
        return analyze_frame_with_vertex_ai(frame_path, ocr_summary=ocr_summary)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return empty_vision_result(
            "Gemini vision is not configured. Set GEMINI_API_KEY."
        )

    image_data = base64.b64encode(frame_path.read_bytes()).decode("ascii")
    timeout_seconds = max(GEMINI_TIMEOUT_MS / 1000, 10.0)

    request_body = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_data,
                        }
                    },
                    {"text": build_vision_prompt(ocr_summary)},
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_RESPONSE_SCHEMA,
            "temperature": 0.2,
        },
    }

    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            params={"key": api_key},
            json=request_body,
            timeout=timeout_seconds,
        )
        if response.status_code >= 400 and "responseSchema" in response.text:
            request_body["generationConfig"] = {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            }
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                params={"key": api_key},
                json=request_body,
                timeout=timeout_seconds,
            )
    except httpx.TimeoutException:
        return empty_vision_result(
            f"Gemini vision timed out after {GEMINI_TIMEOUT_MS} ms."
        )
    except Exception as exc:
        return empty_vision_result(str(exc))

    if response.status_code >= 400:
        return empty_vision_result(f"Gemini vision request failed: {response.text}")

    payload = response.json()
    text, extract_error = extract_gemini_text(payload)
    if extract_error:
        return empty_vision_result(extract_error)

    parsed = parse_json_response(text or "")
    if not parsed:
        preview = (text or "").strip().replace("\n", " ")[:240]
        return empty_vision_result(
            "Gemini returned an unparseable vision response."
            + (f" Preview: {preview}" if preview else "")
        )

    return {
        "ok": True,
        "indicators": normalize_vision_indicators(parsed),
        "error": None,
    }


def analyze_frame_with_vertex_ai(frame_path: Path, *, ocr_summary: str | None = None) -> dict:
    if not VERTEX_AI_PROJECT_ID:
        return empty_vision_result(
            "Vertex AI vision is not configured. Set VERTEX_AI_PROJECT_ID."
        )

    token, token_error = get_vertex_access_token()
    if token_error:
        return empty_vision_result(token_error)

    image_data = base64.b64encode(frame_path.read_bytes()).decode("ascii")
    timeout_seconds = max(GEMINI_TIMEOUT_MS / 1000, 10.0)
    request_body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": image_data,
                        }
                    },
                    {"text": build_vision_prompt(ocr_summary)},
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }
    endpoint = (
        f"https://{VERTEX_AI_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{VERTEX_AI_PROJECT_ID}/locations/{VERTEX_AI_LOCATION}/"
        f"publishers/google/models/{VERTEX_AI_GEMINI_MODEL}:generateContent"
    )

    try:
        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException:
        return empty_vision_result(
            f"Vertex AI vision timed out after {GEMINI_TIMEOUT_MS} ms."
        )
    except Exception as exc:
        return empty_vision_result(str(exc))

    if response.status_code >= 400:
        return empty_vision_result(f"Vertex AI vision request failed: {response.text}")

    payload = response.json()
    text, extract_error = extract_gemini_text(payload)
    if extract_error:
        return empty_vision_result(extract_error)

    parsed = parse_json_response(text or "")
    if not parsed:
        preview = (text or "").strip().replace("\n", " ")[:240]
        return empty_vision_result(
            "Vertex AI returned an unparseable vision response."
            + (f" Preview: {preview}" if preview else "")
        )

    return {
        "ok": True,
        "indicators": normalize_vision_indicators(parsed),
        "error": None,
    }


def analyze_frame_authenticity(frame_path: Path) -> dict:
    if not VISION_ENABLED:
        return empty_authenticity_result("Vision disabled by ENABLE_KEYFRAME_VISION=false.")
    if VISION_PROVIDER != "vertex_ai":
        return empty_authenticity_result(
            "Authenticity pass currently requires VISION_PROVIDER=vertex_ai."
        )
    if not VERTEX_AI_PROJECT_ID:
        return empty_authenticity_result(
            "Vertex AI vision is not configured. Set VERTEX_AI_PROJECT_ID."
        )

    token, token_error = get_vertex_access_token()
    if token_error:
        return empty_authenticity_result(token_error)

    image_data = base64.b64encode(frame_path.read_bytes()).decode("ascii")
    timeout_seconds = max(GEMINI_TIMEOUT_MS / 1000, 10.0)
    request_body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": image_data,
                        }
                    },
                    {"text": AUTHENTICITY_PROMPT},
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }
    endpoint = (
        f"https://{VERTEX_AI_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{VERTEX_AI_PROJECT_ID}/locations/{VERTEX_AI_LOCATION}/"
        f"publishers/google/models/{VERTEX_AI_GEMINI_MODEL}:generateContent"
    )

    try:
        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException:
        return empty_authenticity_result(
            f"Vertex AI authenticity pass timed out after {GEMINI_TIMEOUT_MS} ms."
        )
    except Exception as exc:
        return empty_authenticity_result(str(exc))

    if response.status_code >= 400:
        return empty_authenticity_result(
            f"Vertex AI authenticity pass failed: {response.text}"
        )

    payload = response.json()
    text, extract_error = extract_gemini_text(payload)
    if extract_error:
        return empty_authenticity_result(extract_error)

    parsed = parse_json_response(text or "")
    if not parsed:
        preview = (text or "").strip().replace("\n", " ")[:240]
        return empty_authenticity_result(
            "Vertex AI authenticity pass returned an unparseable response."
            + (f" Preview: {preview}" if preview else "")
        )

    return normalize_authenticity_result(parsed)


def empty_authenticity_result(error: str | None = None) -> dict:
    return {
        "ok": error is None,
        "authenticityRisk": None,
        "riskLevel": "unknown",
        "rationale": "",
        "signals": [],
        "error": error,
    }


def normalize_authenticity_result(parsed: dict) -> dict:
    risk = parsed.get("authenticityRisk")
    if isinstance(risk, (int, float)) and risk == risk:
        risk = max(0.0, min(1.0, float(risk)))
    else:
        risk = None

    risk_level = parsed.get("riskLevel")
    if risk_level not in {"low", "medium", "high"}:
        risk_level = "unknown"

    signals = parsed.get("signals") if isinstance(parsed.get("signals"), list) else []
    return {
        "ok": True,
        "authenticityRisk": risk,
        "riskLevel": risk_level,
        "rationale": str(parsed.get("rationale") or "").strip()[:800],
        "riskSignals": _string_list(parsed.get("riskSignals"), limit=10),
        "realismSignals": _string_list(parsed.get("realismSignals"), limit=10),
        "signals": [str(signal).strip()[:160] for signal in signals[:10] if str(signal).strip()],
        "error": None,
    }


def _string_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:160] for item in value[:limit] if str(item).strip()]


def analyze_event_window_consistency(frames: list[dict]) -> dict:
    if not VISION_ENABLED:
        return empty_event_consistency_result("Vision disabled by ENABLE_KEYFRAME_VISION=false.")
    if VISION_PROVIDER != "vertex_ai":
        return empty_event_consistency_result(
            "Event-window consistency pass currently requires VISION_PROVIDER=vertex_ai."
        )
    if not VERTEX_AI_PROJECT_ID:
        return empty_event_consistency_result(
            "Vertex AI vision is not configured. Set VERTEX_AI_PROJECT_ID."
        )
    if len(frames) < 2:
        return empty_event_consistency_result("Not enough frames for event-window consistency.")

    token, token_error = get_vertex_access_token()
    if token_error:
        return empty_event_consistency_result(token_error)

    timeout_seconds = max(GEMINI_TIMEOUT_MS / 1000, 10.0)
    prompt = (
        EVENT_WINDOW_CONSISTENCY_PROMPT
        + "\n\nFrame metadata JSON:\n"
        + json.dumps(_compact_event_frames(frames), ensure_ascii=False)[:16000]
    )
    request_body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }
    endpoint = (
        f"https://{VERTEX_AI_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{VERTEX_AI_PROJECT_ID}/locations/{VERTEX_AI_LOCATION}/"
        f"publishers/google/models/{VERTEX_AI_GEMINI_MODEL}:generateContent"
    )

    try:
        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException:
        return empty_event_consistency_result(
            f"Vertex AI event-window consistency timed out after {GEMINI_TIMEOUT_MS} ms."
        )
    except Exception as exc:
        return empty_event_consistency_result(str(exc))

    if response.status_code >= 400:
        return empty_event_consistency_result(
            f"Vertex AI event-window consistency failed: {response.text}"
        )

    payload = response.json()
    text, extract_error = extract_gemini_text(payload)
    if extract_error:
        return empty_event_consistency_result(extract_error)

    parsed = parse_json_response(text or "")
    if not parsed:
        preview = (text or "").strip().replace("\n", " ")[:240]
        return empty_event_consistency_result(
            "Vertex AI event-window consistency returned an unparseable response."
            + (f" Preview: {preview}" if preview else "")
        )

    return normalize_event_consistency_result(parsed)


def _compact_event_frames(frames: list[dict]) -> list[dict]:
    compact = []
    for frame in frames[:12]:
        indicators = frame.get("vision", {}).get("indicators", {}) or {}
        authenticity = frame.get("authenticity") or {}
        compact.append(
            {
                "frame": frame.get("frame"),
                "timestamp": frame.get("timestamp"),
                "selectionReason": frame.get("selectionReason"),
                "windowCenterFrame": frame.get("windowCenterFrame"),
                "windowOffsetFrames": frame.get("windowOffsetFrames"),
                "sceneDescription": indicators.get("sceneDescription"),
                "notableObjects": indicators.get("notableObjects", []),
                "notableActions": indicators.get("notableActions", []),
                "destructiveEvent": indicators.get("destructiveEvent"),
                "synthetic": indicators.get("synthetic"),
                "authenticityRisk": authenticity.get("authenticityRisk"),
                "authenticityRiskSignals": authenticity.get("riskSignals", []),
                "authenticityRealismSignals": authenticity.get("realismSignals", []),
                "authenticityRationale": authenticity.get("rationale"),
                "sourceComparison": frame.get("sourceComparison"),
            }
        )
    return compact


def empty_event_consistency_result(error: str | None = None) -> dict:
    return {
        "ok": error is None,
        "physicalConsistencyRisk": None,
        "subjectReactionRisk": None,
        "lightingContinuityRisk": None,
        "debrisMotionRisk": None,
        "cameraContinuityRisk": None,
        "overallTemporalAuthenticityRisk": None,
        "rationale": "",
        "riskSignals": [],
        "consistencySignals": [],
        "error": error,
    }


def normalize_event_consistency_result(parsed: dict) -> dict:
    return {
        "ok": True,
        "physicalConsistencyRisk": _probability(parsed.get("physicalConsistencyRisk")),
        "subjectReactionRisk": _probability(parsed.get("subjectReactionRisk")),
        "lightingContinuityRisk": _probability(parsed.get("lightingContinuityRisk")),
        "debrisMotionRisk": _probability(parsed.get("debrisMotionRisk")),
        "cameraContinuityRisk": _probability(parsed.get("cameraContinuityRisk")),
        "overallTemporalAuthenticityRisk": _probability(
            parsed.get("overallTemporalAuthenticityRisk")
        ),
        "rationale": str(parsed.get("rationale") or "").strip()[:800],
        "riskSignals": _string_list(parsed.get("riskSignals"), limit=12),
        "consistencySignals": _string_list(parsed.get("consistencySignals"), limit=12),
        "error": None,
    }


def _probability(value: object) -> float | None:
    if isinstance(value, (int, float)) and value == value:
        return max(0.0, min(1.0, float(value)))
    return None


def get_vertex_access_token() -> tuple[str | None, str | None]:
    try:
        from google.auth import default as google_auth_default
        from google.auth.transport.requests import Request as GoogleAuthRequest

        credentials, _ = google_auth_default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(GoogleAuthRequest())
        return credentials.token, None
    except Exception as exc:
        return None, (
            "Vertex AI credentials failed. Set GOOGLE_APPLICATION_CREDENTIALS "
            f"to a service account JSON file or run gcloud auth application-default login. {exc}"
        )
