import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(
        TimeoutException=TimeoutError,
        post=MagicMock(),
    )

from pipeline import claim_analysis  # noqa: E402


def visual_frame(**indicator_overrides):
    indicators = {
        "sceneDescription": "A fire and smoke plume next to a road",
        "notableObjects": ["smoke", "road"],
        "notableActions": ["flames rising"],
        "destructiveEvent": {"type": "fire", "confidence": "high"},
        "synthetic": {"aiLikelihood": "high", "signals": ["impossible_smoke"]},
        "visibleText": [],
    }
    indicators.update(indicator_overrides)
    return {"frame": "frame-1.jpg", "timestamp": "00:00:03.000", "vision": {"indicators": indicators}}


class ClaimAnalysisNormalizationTests(unittest.TestCase):
    def test_parse_json_response_accepts_fenced_json_with_surrounding_text(self) -> None:
        parsed = claim_analysis._parse_json_response(
            "```json\n{\"verdict\": \"false\", \"confidence\": 0.8}\n```"
        )

        self.assertEqual(parsed, {"verdict": "false", "confidence": 0.8})

    def test_normalize_claim_analysis_clamps_values_and_floors_false_claim_risk(self) -> None:
        normalized = claim_analysis._normalize_claim_analysis(
            {
                "claim": "A public figure endorsed a fake product",
                "claimType": "identity",
                "verdict": "false",
                "confidence": 1.5,
                "misleadingProbability": 0.1,
                "evidence": [
                    {
                        "sourceTitle": "Fact check",
                        "url": "https://example.com/fact-check",
                        "supports": "contradicts",
                        "note": "The source contradicts the claim.",
                    },
                    "bad evidence entry",
                ],
                "missingContext": ["source", ""],
                "videoSignalsUsed": ["transcript"],
                "recommendedAction": "accept",
            }
        )

        self.assertEqual(normalized["confidence"], 1.0)
        self.assertEqual(normalized["misleadingProbability"], 0.7)
        self.assertEqual(len(normalized["evidence"]), 1)
        self.assertEqual(normalized["evidence"][0]["supports"], "contradicts")
        self.assertEqual(normalized["missingContext"], ["source"])

    def test_visual_authenticity_guardrails_raise_action_and_verdict(self) -> None:
        normalized = {
            "verdict": "true",
            "visualAuthenticityRisk": 0.82,
            "depictedEvent": "fire",
            "recommendedAction": "accept",
            "misleadingProbability": 0.1,
            "summary": "Initial summary.",
        }

        guarded = claim_analysis._apply_visual_authenticity_guardrails(normalized)

        self.assertEqual(guarded["verdict"], "unverified")
        self.assertEqual(guarded["recommendedAction"], "flag_for_review")
        self.assertEqual(guarded["misleadingProbability"], 0.75)
        self.assertIn("Visual authenticity signals", guarded["summary"])

    def test_visual_event_fallback_creates_claim_for_visual_only_video(self) -> None:
        normalized = {
            "claim": None,
            "claimType": "none",
            "verdict": "no_clear_claim",
            "confidence": None,
            "recommendedAction": "needs_more_evidence",
            "misleadingProbability": 0.1,
            "visualAuthenticityRisk": 0.5,
            "visualAuthenticityRationale": "synthetic indicators present",
            "depictedEvent": "fire",
            "summary": "",
            "misleadingProbabilityRationale": "",
        }

        result = claim_analysis._apply_visual_event_fallback(
            normalized,
            keyframe_analysis={"frames": [visual_frame()]},
            visual_event_analysis=None,
        )

        self.assertIn("visually presents", result["claim"])
        self.assertEqual(result["claimType"], "event")
        self.assertEqual(result["verdict"], "unverified")
        self.assertEqual(result["recommendedAction"], "flag_for_review")
        self.assertGreaterEqual(result["misleadingProbability"], 0.45)

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    @patch("pipeline.claim_analysis.httpx.post")
    def test_analyze_claim_normalizes_successful_openai_response(self, mock_post: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output_text": """
            {
              "claim": "The video shows real footage of a fire",
              "claimType": "event",
              "verdict": "true",
              "confidence": 0.9,
              "misleadingProbability": 0.05,
              "visualAuthenticityRisk": 0.1,
              "summary": "Source confirms a similar fire.",
              "evidence": [],
              "missingContext": [],
              "videoSignalsUsed": ["scene context"],
              "recommendedAction": "accept"
            }
            """
        }
        mock_post.return_value = mock_response

        result = claim_analysis.analyze_claim(
            transcript={"text": "This is a fire."},
            keyframe_analysis={"frames": [visual_frame()]},
            temporal_analysis={"summary": {}},
            visual_event_analysis={"summary": {}, "frames": []},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], claim_analysis.OPENAI_CLAIM_MODEL)
        self.assertEqual(result["verdict"], "unverified")
        self.assertEqual(result["recommendedAction"], "flag_for_review")
        self.assertGreaterEqual(result["visualAuthenticityRisk"], 0.72)


if __name__ == "__main__":
    unittest.main()
