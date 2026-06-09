import base64
import json
import os
import shutil
from pathlib import Path
from typing import Any

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
from .download import extract_video_info
from .vision import extract_gemini_text, parse_json_response

CLICKBAIT_PROMPT = """You are analyzing whether a video's thumbnail is clickbait or misleading.
Compare the thumbnail image against the actual video context supplied below.

Flag clickbait when the thumbnail:
- shows a dramatic object, person, event, emotion, danger, result, or text that the video does not support
- exaggerates the video's claim or makes the video seem more shocking than it is
- implies a false or unsupported event
- uses misleading visible text, arrows, circles, fake UI, before/after framing, or unrelated imagery

Do not flag it just because it is visually engaging. Return valid JSON only:
{
  "ok": true,
  "clickbaitScore": 0.0,
  "riskLevel": "low|medium|high",
  "thumbnailSummary": "what the thumbnail appears to show or claim",
  "rationale": "plain-language explanation of why it is or is not clickbait",
  "mismatches": ["specific ways the thumbnail conflicts with the video"],
  "supportingSignals": ["specific ways the thumbnail matches the video"]
}"""


def get_thumbnail_url(video_url: str) -> str | None:
    try:
        info = extract_video_info(video_url)
    except Exception:
        return None
    return get_thumbnail_url_from_info(info)


def get_thumbnail_url_from_info(info: dict[str, Any] | None) -> str | None:
    if not isinstance(info, dict):
        return None

    thumbnails = info.get("thumbnails")
    if isinstance(thumbnails, list):
        for thumbnail in reversed(thumbnails):
            if isinstance(thumbnail, dict) and thumbnail.get("url"):
                return str(thumbnail["url"])

    thumbnail_url = info.get("thumbnail")
    return str(thumbnail_url) if thumbnail_url else None


def download_thumbnail(*, thumbnail_url: str, output_path: Path) -> Path | None:
    try:
        response = httpx.get(thumbnail_url, follow_redirects=True, timeout=30.0)
    except Exception:
        return None

    if response.status_code >= 400 or not response.content:
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    return output_path


def create_thumbnail_fallback(*, keyframe_paths: list[Path], output_path: Path) -> Path | None:
    if not keyframe_paths:
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(keyframe_paths[0], output_path)
    return output_path


def analyze_thumbnail_clickbait(
    *,
    thumbnail_path: Path | None,
    transcript: dict,
    claim_analysis: dict,
    keyframe_analysis: dict,
    visual_event_analysis: dict | None = None,
) -> dict[str, Any]:
    if not thumbnail_path or not thumbnail_path.exists():
        return _empty_clickbait_result("No thumbnail image was available.")
    if not VISION_ENABLED:
        return _empty_clickbait_result("Vision disabled by ENABLE_KEYFRAME_VISION=false.")

    context = _build_context(
        transcript=transcript,
        claim_analysis=claim_analysis,
        keyframe_analysis=keyframe_analysis,
        visual_event_analysis=visual_event_analysis,
    )
    prompt = f"{CLICKBAIT_PROMPT}\n\nActual video context:\n{context}"

    if VISION_PROVIDER == "vertex_ai":
        return _analyze_with_vertex_ai(thumbnail_path, prompt)
    return _analyze_with_gemini_api(thumbnail_path, prompt)


def _analyze_with_gemini_api(thumbnail_path: Path, prompt: str) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return _empty_clickbait_result("Gemini vision is not configured. Set GEMINI_API_KEY.")

    request_body = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": base64.b64encode(thumbnail_path.read_bytes()).decode("ascii"),
                        }
                    },
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1,
        },
    }

    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            params={"key": api_key},
            json=request_body,
            timeout=max(GEMINI_TIMEOUT_MS / 1000, 10.0),
        )
    except httpx.TimeoutException:
        return _empty_clickbait_result(f"Thumbnail analysis timed out after {GEMINI_TIMEOUT_MS} ms.")
    except Exception as exc:
        return _empty_clickbait_result(str(exc))

    if response.status_code >= 400:
        return _empty_clickbait_result(f"Thumbnail analysis failed: {response.text}")

    return _normalize_model_response(response.json())


def _analyze_with_vertex_ai(thumbnail_path: Path, prompt: str) -> dict[str, Any]:
    if not VERTEX_AI_PROJECT_ID:
        return _empty_clickbait_result("Vertex AI vision is not configured. Set VERTEX_AI_PROJECT_ID.")

    from .vision import _get_vertex_access_token

    token, token_error = _get_vertex_access_token()
    if token_error:
        return _empty_clickbait_result(token_error)

    request_body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": base64.b64encode(thumbnail_path.read_bytes()).decode("ascii"),
                        }
                    },
                    {"text": prompt},
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
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=request_body,
            timeout=max(GEMINI_TIMEOUT_MS / 1000, 10.0),
        )
    except httpx.TimeoutException:
        return _empty_clickbait_result(f"Thumbnail analysis timed out after {GEMINI_TIMEOUT_MS} ms.")
    except Exception as exc:
        return _empty_clickbait_result(str(exc))

    if response.status_code >= 400:
        return _empty_clickbait_result(f"Thumbnail analysis failed: {response.text}")

    return _normalize_model_response(response.json())


def _normalize_model_response(payload: dict) -> dict[str, Any]:
    text, error = extract_gemini_text(payload)
    if error:
        return _empty_clickbait_result(error)

    parsed = parse_json_response(text or "")
    if not parsed:
        return _empty_clickbait_result("Thumbnail analysis returned an unparseable response.")

    score = parsed.get("clickbaitScore")
    if isinstance(score, (int, float)) and score == score:
        score = round(max(0.0, min(1.0, float(score))), 4)
    else:
        score = None

    risk_level = parsed.get("riskLevel")
    if risk_level not in {"low", "medium", "high"}:
        if score is None:
            risk_level = "unknown"
        elif score >= 0.7:
            risk_level = "high"
        elif score >= 0.35:
            risk_level = "medium"
        else:
            risk_level = "low"

    return {
        "ok": True,
        "clickbaitScore": score,
        "riskLevel": risk_level,
        "thumbnailSummary": str(parsed.get("thumbnailSummary") or "").strip()[:600],
        "rationale": str(parsed.get("rationale") or "").strip()[:1000],
        "mismatches": _string_list(parsed.get("mismatches"), limit=8),
        "supportingSignals": _string_list(parsed.get("supportingSignals"), limit=8),
        "error": None,
    }


def _build_context(
    *,
    transcript: dict,
    claim_analysis: dict,
    keyframe_analysis: dict,
    visual_event_analysis: dict | None,
) -> str:
    frames = []
    for packet in (keyframe_analysis, visual_event_analysis or {}):
        for frame in (packet.get("frames") or [])[:8]:
            indicators = frame.get("vision", {}).get("indicators", {}) or {}
            frames.append(
                {
                    "timestamp": frame.get("timestamp"),
                    "sceneDescription": indicators.get("sceneDescription"),
                    "visibleText": indicators.get("visibleText"),
                    "notableObjects": indicators.get("notableObjects", []),
                    "notableActions": indicators.get("notableActions", []),
                    "destructiveEvent": indicators.get("destructiveEvent"),
                }
            )

    context = {
        "transcriptPreview": (transcript.get("text") or "")[:3000],
        "claim": claim_analysis.get("claim"),
        "verdict": claim_analysis.get("verdict"),
        "summary": claim_analysis.get("summary"),
        "depictedEvent": claim_analysis.get("depictedEvent"),
        "videoFrameSummaries": frames,
    }
    return json.dumps(context, ensure_ascii=False)[:12000]


def _empty_clickbait_result(error: str | None = None) -> dict[str, Any]:
    return {
        "ok": error is None,
        "clickbaitScore": None,
        "riskLevel": "unknown",
        "thumbnailSummary": "",
        "rationale": "",
        "mismatches": [],
        "supportingSignals": [],
        "error": error,
    }


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:300] for item in value[:limit] if str(item).strip()]
