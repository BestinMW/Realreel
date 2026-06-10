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
Always describe what is visible. sceneDescription must be a non-empty plain-English description for every nonblank image. If the frame is blank, black, blurred beyond recognition, or contains no meaningful content, explicitly say that.
Always list the most important visible objects and actions, even if there is no text overlay and even if nothing suspicious is present.
Read visible signs, labels, captions, posters, storefront text, road signs, UI text, and other readable words.
Only include text that is visible in the image. If uncertain, include the best reading and note uncertainty in context.
Briefly describe the visible scene, objects, and actions, especially destructive events like explosions, fires, collapses, crashes, or smoke.
For explosions, fires, smoke, debris, or collapsing structures, scrutinize whether the event obeys plausible physics across light, shadows, scale, blast direction, debris motion, reflections, smoke behavior, and object continuity.
List observable AI/synthetic visual artifacts such as warped geometry, inconsistent lighting, impossible physics, texture smearing, object disappearance, malformed details, physically implausible explosions, uniform/smeared fire, impossible smoke, or debris that appears/disappears.
Also assess clearly synthetic media even when it is entertainment rather than news: AI-generated music videos, CGI/animation, surreal generated-art scenes, over-smoothed textures, uncanny bodies/faces, dreamlike incoherent objects, artificial depth-of-field, impossible scene composition, and image-generator aesthetics. If the frame appears intentionally AI-generated/CGI/animated, set synthetic.aiLikelihood to medium or high and list the observable synthetic signals.
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
        "sceneDescription": {"type": "string"},
        "notableObjects": {
            "type": "array",
            "items": {"type": "string"},
        },
        "notableActions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "destructiveEvent": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [
                        "explosion",
                        "fire",
                        "collapse",
                        "crash",
                        "smoke",
                        "violence",
                        "none",
                        "unknown",
                    ],
                },
                "confidence": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
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
    "warped_geometry",
    "inconsistent_lighting",
    "impossible_physics",
    "implausible_explosion",
    "impossible_smoke",
    "unnatural_fire",
    "debris_discontinuity",
    "texture_smearing",
    "object_disappearance",
    "malformed_details",
    "cgi_artifacts",
    "cgi_animation",
    "generated_art_aesthetic",
    "surreal_incoherent_scene",
    "uncanny_body",
    "over_smooth_textures",
    "artificial_depth",
    "impossible_scene_composition",
    "ai_music_video_style",
    "none",
}
SYNTHETIC_SIGNAL_ALIASES = {
    "ai generated": "generated_art_aesthetic",
    "ai-generated": "generated_art_aesthetic",
    "generated": "generated_art_aesthetic",
    "generated art": "generated_art_aesthetic",
    "cgi": "cgi_artifacts",
    "computer generated": "cgi_artifacts",
    "animation": "cgi_animation",
    "animated": "cgi_animation",
    "surreal": "surreal_incoherent_scene",
    "dreamlike": "surreal_incoherent_scene",
    "uncanny": "uncanny_body",
    "over smoothed": "over_smooth_textures",
    "oversmoothed": "over_smooth_textures",
}
DESTRUCTIVE_EVENT_TYPES = {
    "explosion",
    "fire",
    "collapse",
    "crash",
    "smoke",
    "violence",
    "none",
    "unknown",
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
    "sceneDescription": "",
    "notableObjects": [],
    "notableActions": [],
    "destructiveEvent": {"type": "unknown", "confidence": "low"},
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
    """Derive OCR-based preprocessing indicators from recognized text lines.

    Args:
        lines (list[dict]): Structured OCR line entries with text, confidence, and
            optional bounding boxes.
        raw (str): Raw OCR text fallback when structured lines are sparse.
        width (float): Image width used to normalize bounding-box ratios.
        height (float): Image height used to normalize bounding-box ratios.

    Returns:
        dict[str, Any]: OCR indicator fields such as ``hasText``, ``lineCount``,
            ``textAreaRatio``, ``likelyHeadline``, and pattern flags.
    """
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
    """Estimate image dimensions from OCR line bounding boxes.

    Args:
        lines (list[dict]): Structured OCR line entries that may include
            ``boundingBox`` coordinates.

    Returns:
        dict[str, float]: ``width`` and ``height`` inferred from the largest
            bounding-box extents, defaulting each to ``1.0`` when unknown.
    """
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
    """Normalize raw vision-model output into the canonical indicator schema.

    Args:
        parsed (Any): Parsed JSON object from a vision model response.

    Returns:
        dict[str, Any]: Sanitized vision indicators with bounded lists, validated
            enums, and defaults from ``DEFAULT_VISION_INDICATORS`` when input is
            invalid.
    """
    if not isinstance(parsed, dict):
        return deepcopy(DEFAULT_VISION_INDICATORS)

    synthetic = parsed.get("synthetic") if isinstance(parsed.get("synthetic"), dict) else {}
    raw_signals = synthetic.get("signals") if isinstance(synthetic.get("signals"), list) else []
    signals = [
        normalized
        for signal in raw_signals
        if (normalized := _normalize_synthetic_signal(signal))
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

    destructive_event = (
        parsed.get("destructiveEvent")
        if isinstance(parsed.get("destructiveEvent"), dict)
        else {}
    )
    destructive_type = destructive_event.get("type")
    destructive_confidence = destructive_event.get("confidence")

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
        "sceneDescription": str(parsed.get("sceneDescription") or "").strip()[:500],
        "notableObjects": _string_items(parsed.get("notableObjects"), limit=12),
        "notableActions": _string_items(parsed.get("notableActions"), limit=12),
        "destructiveEvent": {
            "type": destructive_type
            if destructive_type in DESTRUCTIVE_EVENT_TYPES
            else "unknown",
            "confidence": destructive_confidence
            if destructive_confidence in CONFIDENCE_LEVELS
            else "low",
        },
        "contextSignals": context_signals,
        "visibleText": visible_text,
        "visibleClaimHint": visible_claim_hint,
        "confidence": confidence,
    }


def cross_modal_hints(ocr_indicators: dict, vision_indicators: dict) -> list[dict]:
    """Detect disagreements and notable patterns across OCR and vision indicators.

    Args:
        ocr_indicators (dict): OCR-derived indicator payload.
        vision_indicators (dict): Normalized vision-model indicator payload.

    Returns:
        list[dict]: Cross-modal hint entries with ``type`` and ``confidence`` fields.
    """
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


def _normalize_synthetic_signal(value: Any) -> str | None:
    """Map a raw synthetic-signal label to a canonical enum value.

    Args:
        value (Any): Raw signal string from a vision model response.

    Returns:
        str | None: Canonical synthetic signal name, or ``None`` when the value is
            empty, ``"none"``, or unrecognized.
    """
    if not isinstance(value, str):
        return None

    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned == "none":
        return None
    if cleaned in SYNTHETIC_SIGNAL_VALUES:
        return cleaned

    alias_key = value.strip().lower().replace("_", " ")
    return SYNTHETIC_SIGNAL_ALIASES.get(alias_key)


def format_ocr_summary(indicators: dict) -> str:
    """Format a compact OCR indicator summary for logging or prompts.

    Args:
        indicators (dict): OCR indicator payload, typically from
            ``derive_ocr_indicators``.

    Returns:
        str: Comma-separated summary of key OCR fields, or ``"hasText=false"`` when
            indicators are missing.
    """
    if not indicators:
        return "hasText=false"
    return (
        f"hasText={indicators.get('hasText')},"
        f"lineCount={indicators.get('lineCount')},"
        f"likelyHeadline={indicators.get('likelyHeadline')}"
    )


def seconds_to_timestamp(seconds: float | None) -> str | None:
    """Convert elapsed seconds to an ``HH:MM:SS.mmm`` timestamp string.

    Args:
        seconds (float | None): Elapsed time in seconds, or ``None``.

    Returns:
        str | None: Zero-padded timestamp with millisecond precision, or ``None``
            when ``seconds`` is ``None``.
    """
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
    """Normalize a single vision context-signal entry.

    Args:
        entry (Any): Raw context-signal object from a vision model response.

    Returns:
        dict | None: Normalized ``type`` and ``confidence`` fields, or ``None`` when
            the entry is not a dict.
    """
    if not isinstance(entry, dict):
        return None
    signal_type = entry.get("type")
    confidence = entry.get("confidence")
    return {
        "type": signal_type if signal_type in CONTEXT_SIGNAL_TYPES else "other",
        "confidence": confidence if confidence in CONFIDENCE_LEVELS else "low",
    }


def _normalize_visible_text(entry: Any) -> dict | None:
    """Normalize a single visible-text entry from a vision model response.

    Args:
        entry (Any): Raw visible-text object with text, kind, location, and
            confidence fields.

    Returns:
        dict | None: Trimmed and validated visible-text fields, or ``None`` when the
            entry is invalid or empty.
    """
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


def _string_items(value: Any, *, limit: int) -> list[str]:
    """Extract trimmed non-empty strings from a list-like vision field.

    Args:
        value (Any): Raw list value from a vision model response.
        limit (int): Maximum number of items to retain.

    Returns:
        list[str]: Trimmed string items capped at ``limit`` characters per entry.
    """
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:120] for item in value[:limit] if str(item).strip()]


def _bbox_area(box: dict | None) -> float:
    """Compute the area of an OCR bounding box.

    Args:
        box (dict | None): Bounding box with ``x0``, ``y0``, ``x1``, and ``y1``
            coordinates.

    Returns:
        float: Non-negative rectangle area, or ``0.0`` when the box is missing.
    """
    if not box:
        return 0.0
    return max(0.0, box["x1"] - box["x0"]) * max(0.0, box["y1"] - box["y0"])
