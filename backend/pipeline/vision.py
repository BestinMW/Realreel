import base64
import json
import os
import re
from copy import deepcopy
from pathlib import Path

import httpx

from .config import GEMINI_MODEL, GEMINI_TIMEOUT_MS, VISION_ENABLED
from .indicators import (
    DEFAULT_VISION_INDICATORS,
    GEMINI_RESPONSE_SCHEMA,
    VISION_PROMPT,
    normalize_vision_indicators,
)


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
