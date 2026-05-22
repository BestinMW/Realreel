import base64
import json
import os
import re
from copy import deepcopy
from pathlib import Path

import httpx

from .config import GEMINI_MODEL, GEMINI_TIMEOUT_MS, VISION_ENABLED
from .indicators import DEFAULT_VISION_INDICATORS, VISION_PROMPT, normalize_vision_indicators


def empty_vision_result(error: str | None = None) -> dict:
    return {
        "ok": error is None,
        "indicators": deepcopy(DEFAULT_VISION_INDICATORS),
        "error": error,
    }


def build_vision_prompt(ocr_summary: str | None) -> str:
    if not ocr_summary:
        return VISION_PROMPT
    return f"{VISION_PROMPT}\n\nOCR preprocessing summary (do not re-transcribe): {ocr_summary}"


def parse_json_response(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def analyze_frame_with_gemini(frame_path: Path, *, ocr_summary: str | None = None) -> dict:
    if not VISION_ENABLED:
        return empty_vision_result("Gemini vision disabled by ENABLE_KEYFRAME_VISION=false.")

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return empty_vision_result(
            "Gemini vision is not configured. Set GEMINI_API_KEY."
        )

    image_data = base64.b64encode(frame_path.read_bytes()).decode("ascii")
    timeout_seconds = GEMINI_TIMEOUT_MS / 1000

    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            params={"key": api_key},
            json={
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
                "generationConfig": {"responseMimeType": "application/json"},
            },
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
    text = (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    parsed = parse_json_response(text)
    if not parsed:
        return empty_vision_result("Gemini returned an unparseable vision response.")

    return {
        "ok": True,
        "indicators": normalize_vision_indicators(parsed),
        "error": None,
    }
