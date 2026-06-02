import re
from copy import deepcopy
from typing import Any

SCHEMA_VERSION = "1"

DATE_LIKE_PATTERN = re.compile(
    r"\b(?:(?:19|20)\d{2}|\d{1,2}[\/\-\.]\d{1,2}(?:[\/\-\.]\d{2,4})?|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b",
    re.IGNORECASE,
)

VISION_PROMPT = """Extract preprocessing indicators from this video keyframe.
Return valid JSON only (use true/false for booleans, not the word boolean).
Read visible signs, labels, captions, posters, storefront text, road signs, UI text, and other readable words.
Only include text that is visible in the image. If uncertain, include the best reading and note uncertainty in context.
Do NOT conclude the video is misleading or fake; only list observable signals."""

GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "medium": {
            "type": "string",
            "enum": [
                "live_action",
                "animation",
                "screen_recording",
                "mixed",
                "unknown",
            ],
        },
        "hasTextOverlay": {"type": "boolean"},
        "hasNewsStyleGraphics": {"type": "boolean"},
        "hasChartOrGraph": {"type": "boolean"},
        "hasSocialMediaUI": {"type": "boolean"},
        "appearsScreenshot": {"type": "boolean"},
        "peopleCount": {
            "type": "string",
            "enum": ["none", "one", "few", "many", "unknown"],
        },
        "faceVisible": {"type": "boolean"},
        "synthetic": {
            "type": "object",
            "properties": {
                "aiLikelihood": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "unknown"],
                },
                "signals": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "contextSignals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                },
            },
        },
        "visibleText": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "sign",
                            "label",
                            "caption",
                            "poster",
                            "storefront",
                            "road_sign",
                            "ui_text",
                            "other",
                        ],
                    },
                    "location": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                },
            },
        },
        "visibleClaimHint": {"type": "string"},
        "confidence": {"type": "number"},
    },
}

MEDIUM_VALUES = {
    "live_action",
    "animation",
    "screen_recording",
    "mixed",
    "unknown",
}
PEOPLE_COUNT_VALUES = {"none", "one", "few", "many", "unknown"}
AI_LIKELIHOOD_VALUES = {"low", "medium", "high", "unknown"}
SYNTHETIC_SIGNAL_VALUES = {
    "watermark_visible",
    "unnatural_face",
    "warped_text",
    "inconsistent_lighting",
    "cgi_artifacts",
    "none",
}
CONTEXT_SIGNAL_TYPES = {
    "stock_broll",
    "urgent_overlay_on_calm_scene",
    "chart_no_source",
    "stale_looking_footage",
    "possible_deepfake",
    "other",
}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
VISIBLE_TEXT_KINDS = {
    "sign",
    "label",
    "caption",
    "poster",
    "storefront",
    "road_sign",
    "ui_text",
    "other",
}

DEFAULT_VISION_INDICATORS: dict[str, Any] = {
    "medium": "unknown",
    "hasTextOverlay": False,
    "hasNewsStyleGraphics": False,
    "hasChartOrGraph": False,
    "hasSocialMediaUI": False,
    "appearsScreenshot": False,
    "peopleCount": "unknown",
    "faceVisible": False,
    "synthetic": {"aiLikelihood": "unknown", "signals": []},
    "contextSignals": [],
    "visibleText": [],
    "visibleClaimHint": None,
    "confidence": None,
}


def derive_ocr_indicators(
    lines: list[dict],
    raw: str,
    width: float = 1,
    height: float = 1,
) -> dict[str, Any]:
    has_text = len(lines) > 0 or bool(raw)
    joined = raw or " ".join(line["text"] for line in lines)
    top_lines = [
        line
        for line in lines
        if (line.get("boundingBox") or {}).get("y0", height) < height * 0.35
    ]
    text_area = sum(_bbox_area(line.get("boundingBox")) for line in lines)
    image_area = max(width * height, 1)

    avg_confidence = None
    if lines:
        avg_confidence = round(
            sum(line["confidence"] for line in lines) / len(lines),
            2,
        )

    return {
        "hasText": has_text,
        "lineCount": len(lines),
        "textAreaRatio": min(1.0, round(text_area / image_area, 4)),
        "likelyHeadline": (
            len(top_lines) > 0
            and len(top_lines) <= 2
            and any(len(line["text"]) > 8 for line in top_lines)
        ),
        "hasNumbers": bool(re.search(r"\d", joined)),
        "hasUrl": bool(re.search(r"https?://|www\.", joined, re.IGNORECASE)),
        "hasDateLike": bool(DATE_LIKE_PATTERN.search(joined)),
        "hasAllCapsWords": bool(re.search(r"\b[A-Z]{4,}\b", joined)),
        "avgLineConfidence": avg_confidence,
    }


def estimate_image_size_from_lines(lines: list[dict]) -> dict[str, float]:
    width = 0.0
    height = 0.0
    for line in lines:
        box = line.get("boundingBox")
        if not box:
            continue
        width = max(width, box["x1"])
        height = max(height, box["y1"])
    return {"width": width or 1.0, "height": height or 1.0}


def normalize_vision_indicators(parsed: Any) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return deepcopy(DEFAULT_VISION_INDICATORS)

    synthetic = parsed.get("synthetic") if isinstance(parsed.get("synthetic"), dict) else {}
    raw_signals = synthetic.get("signals") if isinstance(synthetic.get("signals"), list) else []
    signals = [
        signal
        for signal in raw_signals
        if signal in SYNTHETIC_SIGNAL_VALUES and signal != "none"
    ][:8]

    context_signals = [
        normalized
        for entry in (parsed.get("contextSignals") or [])
        if (normalized := _normalize_context_signal(entry))
    ][:6]

    visible_text = [
        normalized
        for entry in (parsed.get("visibleText") or [])
        if (normalized := _normalize_visible_text(entry))
    ][:12]

    visible_claim_hint = parsed.get("visibleClaimHint")
    if isinstance(visible_claim_hint, str) and visible_claim_hint.strip():
        visible_claim_hint = visible_claim_hint.strip()[:200]
    else:
        visible_claim_hint = None

    confidence = parsed.get("confidence")
    if isinstance(confidence, (int, float)) and confidence == confidence:
        confidence = max(0.0, min(1.0, float(confidence)))
    else:
        confidence = None

    return {
        "medium": parsed.get("medium")
        if parsed.get("medium") in MEDIUM_VALUES
        else "unknown",
        "hasTextOverlay": bool(parsed.get("hasTextOverlay")),
        "hasNewsStyleGraphics": bool(parsed.get("hasNewsStyleGraphics")),
        "hasChartOrGraph": bool(parsed.get("hasChartOrGraph")),
        "hasSocialMediaUI": bool(parsed.get("hasSocialMediaUI")),
        "appearsScreenshot": bool(parsed.get("appearsScreenshot")),
        "peopleCount": parsed.get("peopleCount")
        if parsed.get("peopleCount") in PEOPLE_COUNT_VALUES
        else "unknown",
        "faceVisible": bool(parsed.get("faceVisible")),
        "synthetic": {
            "aiLikelihood": synthetic.get("aiLikelihood")
            if synthetic.get("aiLikelihood") in AI_LIKELIHOOD_VALUES
            else "unknown",
            "signals": signals,
        },
        "contextSignals": context_signals,
        "visibleText": visible_text,
        "visibleClaimHint": visible_claim_hint,
        "confidence": confidence,
    }


def cross_modal_hints(ocr_indicators: dict, vision_indicators: dict) -> list[dict]:
    hints: list[dict] = []
    if not ocr_indicators or not vision_indicators:
        return hints

    if ocr_indicators.get("hasText") and not vision_indicators.get("hasTextOverlay"):
        hints.append({"type": "ocr_vision_text_disagreement", "confidence": "low"})

    if ocr_indicators.get("likelyHeadline") and vision_indicators.get("medium") == "live_action":
        hints.append({"type": "headline_over_footage_candidate", "confidence": "medium"})

    if ocr_indicators.get("hasUrl") and not vision_indicators.get("hasSocialMediaUI"):
        hints.append({"type": "url_in_ocr_without_social_ui", "confidence": "low"})

    synthetic = vision_indicators.get("synthetic") or {}
    if synthetic.get("aiLikelihood") == "high" and synthetic.get("signals"):
        hints.append({"type": "synthetic_visual_signals", "confidence": "medium"})

    return hints


def format_ocr_summary(indicators: dict) -> str:
    if not indicators:
        return "hasText=false"
    return (
        f"hasText={indicators.get('hasText')},"
        f"lineCount={indicators.get('lineCount')},"
        f"likelyHeadline={indicators.get('likelyHeadline')}"
    )


def seconds_to_timestamp(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    safe_seconds = max(0.0, float(seconds))
    hours = int(safe_seconds // 3600)
    minutes = int((safe_seconds % 3600) // 60)
    whole_seconds = int(safe_seconds % 60)
    milliseconds = int(round((safe_seconds - int(safe_seconds)) * 1000))
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}."
        f"{milliseconds:03d}"
    )


def _normalize_context_signal(entry: Any) -> dict | None:
    if not isinstance(entry, dict):
        return None
    signal_type = entry.get("type")
    confidence = entry.get("confidence")
    return {
        "type": signal_type if signal_type in CONTEXT_SIGNAL_TYPES else "other",
        "confidence": confidence if confidence in CONFIDENCE_LEVELS else "low",
    }


def _normalize_visible_text(entry: Any) -> dict | None:
    if not isinstance(entry, dict):
        return None

    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    kind = entry.get("kind")
    location = entry.get("location")
    confidence = entry.get("confidence")

    return {
        "text": text.strip()[:300],
        "kind": kind if kind in VISIBLE_TEXT_KINDS else "other",
        "location": location.strip()[:120]
        if isinstance(location, str) and location.strip()
        else None,
        "confidence": confidence if confidence in CONFIDENCE_LEVELS else "low",
    }


def _bbox_area(box: dict | None) -> float:
    if not box:
        return 0.0
    return max(0.0, box["x1"] - box["x0"]) * max(0.0, box["y1"] - box["y0"])
