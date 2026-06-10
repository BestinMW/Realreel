"""Unit tests for claim analysis normalization in the engine layer.

OpenAI HTTP calls are mocked — these tests run without an API key.

Run:
    pytest tests/engine/test_claim_analysis_units.py -v
"""

import os
from unittest.mock import MagicMock, patch

from pipeline import claim_analysis


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
    return {
        "frame": "frame-1.jpg",
        "timestamp": "00:00:03.000",
        "vision": {"indicators": indicators},
    }


# ---------------------------------------------------------------------------
# Test 1: _parse_json_response — fenced JSON with surrounding text
# ---------------------------------------------------------------------------
def test_parse_json_response_accepts_fenced_json_with_surrounding_text():
    parsed = claim_analysis._parse_json_response(
        '```json\n{"verdict": "false", "confidence": 0.8}\n```'
    )
    assert parsed == {"verdict": "false", "confidence": 0.8}


# ---------------------------------------------------------------------------
# Test 2: _normalize_claim_analysis — clamps values and floors false-claim risk
# ---------------------------------------------------------------------------
def test_normalize_claim_analysis_clamps_values_and_floors_false_claim_risk():
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

    assert normalized["confidence"] == 1.0
    assert normalized["misleadingProbability"] == 0.7
    assert len(normalized["evidence"]) == 1
    assert normalized["evidence"][0]["supports"] == "contradicts"
    assert normalized["missingContext"] == ["source"]


# ---------------------------------------------------------------------------
# Test 3: _apply_visual_authenticity_guardrails — raises action and verdict
# ---------------------------------------------------------------------------
def test_visual_authenticity_guardrails_raise_action_and_verdict():
    normalized = {
        "verdict": "true",
        "visualAuthenticityRisk": 0.82,
        "depictedEvent": "fire",
        "recommendedAction": "accept",
        "misleadingProbability": 0.1,
        "summary": "Initial summary.",
    }

    guarded = claim_analysis._apply_visual_authenticity_guardrails(normalized)

    assert guarded["verdict"] == "unverified"
    assert guarded["recommendedAction"] == "flag_for_review"
    assert guarded["misleadingProbability"] == 0.75
    assert "Visual authenticity signals" in guarded["summary"]


# ---------------------------------------------------------------------------
# Test 4: _apply_visual_event_fallback — creates claim for visual-only video
# ---------------------------------------------------------------------------
def test_visual_event_fallback_creates_claim_for_visual_only_video():
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

    assert "visually presents" in result["claim"]
    assert result["claimType"] == "event"
    assert result["verdict"] == "unverified"
    assert result["recommendedAction"] == "flag_for_review"
    assert result["misleadingProbability"] >= 0.45


# ---------------------------------------------------------------------------
# Test 5: analyze_claim — normalizes successful OpenAI response
# ---------------------------------------------------------------------------
@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
@patch("pipeline.claim_analysis.httpx.post")
def test_analyze_claim_normalizes_successful_openai_response(mock_post):
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

    assert result["ok"] is True
    assert result["model"] == claim_analysis.OPENAI_CLAIM_MODEL
    assert result["verdict"] == "unverified"
    assert result["recommendedAction"] == "flag_for_review"
    assert result["visualAuthenticityRisk"] >= 0.72
