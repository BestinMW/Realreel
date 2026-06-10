import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from pipeline.indicators import (  # noqa: E402
    cross_modal_hints,
    derive_ocr_indicators,
    estimate_image_size_from_lines,
    format_ocr_summary,
    normalize_vision_indicators,
    seconds_to_timestamp,
)


class OcrIndicatorTests(unittest.TestCase):
    def test_derive_ocr_indicators_detects_headline_numbers_url_and_date(self) -> None:
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

        self.assertTrue(indicators["hasText"])
        self.assertEqual(indicators["lineCount"], 2)
        self.assertTrue(indicators["likelyHeadline"])
        self.assertTrue(indicators["hasNumbers"])
        self.assertTrue(indicators["hasUrl"])
        self.assertTrue(indicators["hasDateLike"])
        self.assertTrue(indicators["hasAllCapsWords"])
        self.assertEqual(indicators["avgLineConfidence"], 90.0)
        self.assertEqual(indicators["textAreaRatio"], 0.105)

    def test_estimate_image_size_uses_largest_bounding_box_edges(self) -> None:
        size = estimate_image_size_from_lines(
            [
                {"boundingBox": {"x0": 0, "y0": 0, "x1": 120, "y1": 45}},
                {"boundingBox": {"x0": 10, "y0": 80, "x1": 300, "y1": 160}},
                {"text": "missing box is ignored"},
            ]
        )

        self.assertEqual(size, {"width": 300, "height": 160})

    def test_seconds_to_timestamp_clamps_negative_values_and_preserves_ms(self) -> None:
        self.assertEqual(seconds_to_timestamp(-4), "00:00:00.000")
        self.assertEqual(seconds_to_timestamp(3661.25), "01:01:01.250")
        self.assertIsNone(seconds_to_timestamp(None))

    def test_format_ocr_summary_is_stable_for_empty_and_populated_indicators(self) -> None:
        self.assertEqual(format_ocr_summary({}), "hasText=false")
        self.assertEqual(
            format_ocr_summary(
                {"hasText": True, "lineCount": 3, "likelyHeadline": False}
            ),
            "hasText=True,lineCount=3,likelyHeadline=False",
        )


class VisionIndicatorTests(unittest.TestCase):
    def test_normalize_vision_indicators_clamps_and_filters_model_output(self) -> None:
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

        self.assertEqual(normalized["medium"], "live_action")
        self.assertTrue(normalized["hasTextOverlay"])
        self.assertEqual(normalized["peopleCount"], "unknown")
        self.assertEqual(
            normalized["synthetic"]["signals"],
            ["generated_art_aesthetic", "warped_geometry"],
        )
        self.assertEqual(normalized["destructiveEvent"]["type"], "explosion")
        self.assertEqual(normalized["contextSignals"][1]["type"], "other")
        self.assertEqual(normalized["contextSignals"][1]["confidence"], "low")
        self.assertEqual(normalized["visibleText"][1]["kind"], "other")
        self.assertEqual(normalized["visibleText"][1]["confidence"], "low")
        self.assertEqual(normalized["visibleClaimHint"], "Explosion downtown")
        self.assertEqual(normalized["confidence"], 1.0)

    def test_cross_modal_hints_flags_disagreements_and_synthetic_signals(self) -> None:
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

        self.assertEqual(
            {hint["type"] for hint in hints},
            {
                "ocr_vision_text_disagreement",
                "headline_over_footage_candidate",
                "url_in_ocr_without_social_ui",
                "synthetic_visual_signals",
            },
        )


if __name__ == "__main__":
    unittest.main()
