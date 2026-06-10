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
    """Build a standardized vision result with default indicators and no analysis.

    Args:
        error (str | None): Optional error message; when set, ``ok`` is ``False``.

    Returns:
        dict: Payload with ``ok`` (``True`` when ``error`` is ``None``),
            ``indicators`` (deep copy of ``DEFAULT_VISION_INDICATORS``), and
            ``error`` (``None`` on success or the provided error string).
    """
    return {
        "ok": error is None,
        "indicators": deepcopy(DEFAULT_VISION_INDICATORS),
        "error": error,
    }


def build_vision_prompt(ocr_summary: str | None) -> str:
    """Compose the Gemini vision prompt, optionally augmented with OCR context.

    Args:
        ocr_summary (str | None): Tesseract OCR summary to append as context, or
            ``None`` to use the base prompt only.

    Returns:
        str: ``VISION_PROMPT`` alone, or ``VISION_PROMPT`` followed by the OCR
            preprocessing summary when ``ocr_summary`` is non-empty.
    """
    if not ocr_summary:
        return VISION_PROMPT
    return (
        f"{VISION_PROMPT}\n\n"
        "OCR preprocessing summary from Tesseract. Use this as context, but still "
        f"read visible text yourself when possible: {ocr_summary}"
    )


def _strip_code_fence(text: str) -> str:
    """Remove leading and trailing Markdown code fences from model output text.

    Args:
        text (str): Raw text that may be wrapped in `` ``` `` or `` ```json `` fences.

    Returns:
        str: ``text`` with outer code fences stripped and whitespace trimmed; unchanged
            apart from trimming when no fence is present.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _repair_json_text(text: str) -> str:
    """Apply heuristic fixes to malformed JSON text from model responses.

    Args:
        text (str): JSON-like string that may contain schema placeholders or trailing
            commas.

    Returns:
        str: Repaired text with ``: boolean`` and ``: string`` placeholders replaced,
            and trailing commas before ``}`` or ``]`` removed.
    """
    repaired = text
    repaired = repaired.replace(": boolean", ": false")
    repaired = repaired.replace(": string", ':""')
    repaired = re.sub(r",\s*}", "}", repaired)
    repaired = re.sub(r",\s*]", "]", repaired)
    return repaired


def parse_json_response(text: str) -> dict | None:
    """Parse a JSON object from Gemini or Vertex AI response text.

    Args:
        text (str): Raw model output that may include code fences or embedded JSON.

    Returns:
        dict | None: Parsed JSON object on success, or ``None`` when ``text`` is
            empty, not valid JSON, or contains no parseable object.
    """
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
    """Extract concatenated text from a Gemini or Vertex AI generateContent payload.

    Args:
        payload (dict): Raw API response body from ``generateContent``.

    Returns:
        tuple[str | None, str | None]: ``(text, None)`` when candidate text is
            present; ``(None, error_message)`` when the request was blocked, no
            candidates were returned, finish reason is non-terminal, or text parts
            are empty.
    """
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
    """Analyze a single frame with the Gemini API and return vision indicators.

    Args:
        frame_path (Path): Path to the JPEG frame image to analyze.
        ocr_summary (str | None): Optional OCR summary passed into the vision prompt.

    Returns:
        dict: ``empty_vision_result`` with an ``error`` string when vision is disabled,
            credentials are missing, the request times out or fails, or the response is
            unparseable; otherwise ``{"ok": True, "indicators": ..., "error": None}``.
            Delegates to ``analyze_frame_with_vertex_ai`` when
            ``VISION_PROVIDER`` is ``"vertex_ai"``.
    """
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
    """Analyze a single frame with Vertex AI Gemini and return vision indicators.

    Args:
        frame_path (Path): Path to the JPEG frame image to analyze.
        ocr_summary (str | None): Optional OCR summary passed into the vision prompt.

    Returns:
        dict: ``empty_vision_result`` with an ``error`` string when
            ``VERTEX_AI_PROJECT_ID`` is unset, credentials fail, the request times
            out or fails, or the response is unparseable; otherwise
            ``{"ok": True, "indicators": ..., "error": None}``.
    """
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
    """Assess whether a single frame appears authentic using Vertex AI Gemini.

    Args:
        frame_path (Path): Path to the JPEG frame image to assess.

    Returns:
        dict: ``empty_authenticity_result`` with an ``error`` string when vision is
            disabled, ``VISION_PROVIDER`` is not ``"vertex_ai"``, Vertex AI is
            unconfigured, credentials fail, the request times out or fails, or the
            response is unparseable; otherwise a normalized authenticity payload from
            ``normalize_authenticity_result`` with ``ok`` ``True``.
    """
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
    """Build a standardized authenticity result with no risk assessment.

    Args:
        error (str | None): Optional error message; when set, ``ok`` is ``False``.

    Returns:
        dict: Payload with ``ok`` (``True`` when ``error`` is ``None``),
            ``authenticityRisk`` (``None``), ``riskLevel`` (``"unknown"``),
            empty ``rationale`` and ``signals``, and ``error``.
    """
    return {
        "ok": error is None,
        "authenticityRisk": None,
        "riskLevel": "unknown",
        "rationale": "",
        "signals": [],
        "error": error,
    }


def normalize_authenticity_result(parsed: dict) -> dict:
    """Normalize a parsed authenticity JSON object into a stable result shape.

    Args:
        parsed (dict): Raw JSON object from an authenticity model response.

    Returns:
        dict: Payload with ``ok`` ``True``, clamped ``authenticityRisk`` (``float`` or
            ``None``), ``riskLevel`` (``"low"``, ``"medium"``, ``"high"``, or
            ``"unknown"``), trimmed ``rationale``, ``riskSignals``,
            ``realismSignals``, legacy ``signals``, and ``error`` ``None``.
    """
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
    """Coerce a value into a bounded list of trimmed non-empty strings.

    Args:
        value (object): Candidate list from parsed model JSON.
        limit (int): Maximum number of items to include.

    Returns:
        list[str]: Up to ``limit`` stripped strings truncated to 160 characters; ``[]``
            when ``value`` is not a list or contains no non-empty entries.
    """
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:160] for item in value[:limit] if str(item).strip()]


def analyze_event_window_consistency(frames: list[dict]) -> dict:
    """Assess cross-frame physical and temporal consistency for an event window.

    Args:
        frames (list[dict]): Frame metadata dicts in timestamp order, each with vision
            and authenticity fields used to build the prompt.

    Returns:
        dict: ``empty_event_consistency_result`` with an ``error`` string when vision
            is disabled, ``VISION_PROVIDER`` is not ``"vertex_ai"``, Vertex AI is
            unconfigured, fewer than two frames are supplied, credentials fail, the
            request times out or fails, or the response is unparseable; otherwise a
            normalized consistency payload from ``normalize_event_consistency_result``
            with ``ok`` ``True``.
    """
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
    """Reduce frame metadata to the fields needed for event-window consistency.

    Args:
        frames (list[dict]): Full per-frame metadata including vision and authenticity.

    Returns:
        list[dict]: Up to 12 compact dicts with frame index, timestamp, selection
            metadata, key vision indicators, authenticity fields, and
            ``sourceComparison``.
    """
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
    """Build a standardized event-window consistency result with no risk scores.

    Args:
        error (str | None): Optional error message; when set, ``ok`` is ``False``.

    Returns:
        dict: Payload with ``ok`` (``True`` when ``error`` is ``None``), all risk
            fields set to ``None``, empty ``rationale``, ``riskSignals``, and
            ``consistencySignals``, and ``error``.
    """
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
    """Normalize a parsed event-window consistency JSON object into a stable shape.

    Args:
        parsed (dict): Raw JSON object from an event-window consistency model response.

    Returns:
        dict: Payload with ``ok`` ``True``, clamped probability fields (``float`` or
            ``None`` for each risk metric), trimmed ``rationale``, ``riskSignals``,
            ``consistencySignals``, and ``error`` ``None``.
    """
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
    """Clamp a numeric value to a valid probability in ``[0.0, 1.0]``.

    Args:
        value (object): Candidate probability from parsed model JSON.

    Returns:
        float | None: ``value`` as a float clamped to ``[0.0, 1.0]`` when it is a
            finite ``int`` or ``float``; otherwise ``None``.
    """
    if isinstance(value, (int, float)) and value == value:
        return max(0.0, min(1.0, float(value)))
    return None


def get_vertex_access_token() -> tuple[str | None, str | None]:
    """Obtain a Google Cloud access token for Vertex AI API requests.

    Args:
        None

    Returns:
        tuple[str | None, str | None]: ``(token, None)`` when Application Default
            Credentials refresh succeeds; ``(None, error_message)`` when credential
            loading or refresh fails.
    """
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
