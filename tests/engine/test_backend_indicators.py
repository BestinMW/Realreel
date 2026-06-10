"""Unit tests for OCR and vision indicator normalization in the engine layer.

Run:
    pytest tests/engine/test_backend_indicators.py -v
"""

from pipeline.indicators import (
    cross_modal_hints,
    derive_ocr_indicators,
    estimate_image_size_from_lines,
    format_ocr_summary,
    normalize_vision_indicators,
    seconds_to_timestamp,
)


# ---------------------------------------------------------------------------
# Test 1: derive_ocr_indicators — headline, numbers, URL, and date signals
# ---------------------------------------------------------------------------
def test_derive_ocr_indicators_detects_headline_numbers_url_and_date():
    lines = [
        {
            "text": "BREAKING: FLOOD UPDATE 6/8/2026",
            "confidence": 87,
            "boundingBox": {"x0": 10, "y0": 10, "x1": 310, "y1": 50},
        },
        {
            "text": "www.example.com",
            "confidence": 93,
            "boundingBox": {"x0": 20, "y0": 300, "x1": 180, "y1": 330},
        },
    ]

    indicators = derive_ocr_indicators(lines, raw="", width=400, height=400)

    assert indicators["hasText"] is True
    assert indicators["lineCount"] == 2
    assert indicators["likelyHeadline"] is True
    assert indicators["hasNumbers"] is True
    assert indicators["hasUrl"] is True
    assert indicators["hasDateLike"] is True
    assert indicators["hasAllCapsWords"] is True
    assert indicators["avgLineConfidence"] == 90.0
    assert indicators["textAreaRatio"] == 0.105


# ---------------------------------------------------------------------------
# Test 2: estimate_image_size_from_lines — largest bounding box edges
# ---------------------------------------------------------------------------
def test_estimate_image_size_uses_largest_bounding_box_edges():
    size = estimate_image_size_from_lines(
        [
            {"boundingBox": {"x0": 0, "y0": 0, "x1": 120, "y1": 45}},
            {"boundingBox": {"x0": 10, "y0": 80, "x1": 300, "y1": 160}},
            {"text": "missing box is ignored"},
        ]
    )

    assert size == {"width": 300, "height": 160}


# ---------------------------------------------------------------------------
# Test 3: seconds_to_timestamp — clamps negatives and preserves milliseconds
# ---------------------------------------------------------------------------
def test_seconds_to_timestamp_clamps_negative_values_and_preserves_ms():
    assert seconds_to_timestamp(-4) == "00:00:00.000"
    assert seconds_to_timestamp(3661.25) == "01:01:01.250"
    assert seconds_to_timestamp(None) is None


# ---------------------------------------------------------------------------
# Test 4: format_ocr_summary — stable for empty and populated indicators
# ---------------------------------------------------------------------------
def test_format_ocr_summary_is_stable_for_empty_and_populated_indicators():
    assert format_ocr_summary({}) == "hasText=false"
    assert (
        format_ocr_summary({"hasText": True, "lineCount": 3, "likelyHeadline": False})
        == "hasText=True,lineCount=3,likelyHeadline=False"
    )


# ---------------------------------------------------------------------------
# Test 5: normalize_vision_indicators — clamps and filters model output
# ---------------------------------------------------------------------------
def test_normalize_vision_indicators_clamps_and_filters_model_output():
    normalized = normalize_vision_indicators(
        {
            "medium": "live_action",
            "hasTextOverlay": 1,
            "peopleCount": "crowd",
            "synthetic": {
                "aiLikelihood": "high",
                "signals": [
                    "AI generated",
                    "none",
                    "warped geometry",
                    "not-real-signal",
                ],
            },
            "sceneDescription": "  A large plume of smoke near a roadway.  ",
            "notableObjects": ["smoke", "road", ""],
            "notableActions": ["people running"],
            "destructiveEvent": {"type": "explosion", "confidence": "high"},
            "contextSignals": [
                {"type": "stale_looking_footage", "confidence": "medium"},
                {"type": "unsupported", "confidence": "certain"},
                "bad entry",
            ],
            "visibleText": [
                {
                    "text": "BREAKING",
                    "kind": "caption",
                    "location": "top",
                    "confidence": "high",
                },
                {"text": "   "},
                {"text": "Source?", "kind": "mystery", "confidence": "certain"},
            ],
            "visibleClaimHint": "  Explosion downtown  ",
            "confidence": 1.8,
        }
    )

    assert normalized["medium"] == "live_action"
    assert normalized["hasTextOverlay"] is True
    assert normalized["peopleCount"] == "unknown"
    assert normalized["synthetic"]["signals"] == [
        "generated_art_aesthetic",
        "warped_geometry",
    ]
    assert normalized["destructiveEvent"]["type"] == "explosion"
    assert normalized["contextSignals"][1]["type"] == "other"
    assert normalized["contextSignals"][1]["confidence"] == "low"
    assert normalized["visibleText"][1]["kind"] == "other"
    assert normalized["visibleText"][1]["confidence"] == "low"
    assert normalized["visibleClaimHint"] == "Explosion downtown"
    assert normalized["confidence"] == 1.0


# ---------------------------------------------------------------------------
# Test 6: cross_modal_hints — disagreements and synthetic signals
# ---------------------------------------------------------------------------
def test_cross_modal_hints_flags_disagreements_and_synthetic_signals():
    hints = cross_modal_hints(
        {
            "hasText": True,
            "likelyHeadline": True,
            "hasUrl": True,
        },
        {
            "hasTextOverlay": False,
            "medium": "live_action",
            "hasSocialMediaUI": False,
            "synthetic": {
                "aiLikelihood": "high",
                "signals": ["warped_geometry"],
            },
        },
    )

    assert {hint["type"] for hint in hints} == {
        "ocr_vision_text_disagreement",
        "headline_over_footage_candidate",
        "url_in_ocr_without_social_ui",
        "synthetic_visual_signals",
    }
