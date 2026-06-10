"""Unit tests for interface-layer reliability score display logic.

Mirrors `getReliabilityScore()` in `frontend/app/page.tsx` so the UI
formula can be tested without a Node test runner.

Run:
    pytest tests/interface/test_reliability.py -v
"""


def compute_reliability_score(result: dict | None) -> int | None:
    """Same contract as the frontend reliability score helper."""
    if not result:
        return None

    misleading_risk = result.get("misleadingProbability")
    visual_risk = result.get("visualAuthenticityRisk")
    thumbnail_risk = result.get("thumbnailClickbaitScore")
    repost_risk = result.get("repostRisk")

    risks = [
        value
        for value in (misleading_risk, visual_risk, thumbnail_risk, repost_risk)
        if isinstance(value, (int, float))
    ]
    if risks:
        highest_risk = max(risks)
        return max(0, min(100, round((1 - highest_risk) * 100)))

    claim_confidence = result.get("claimConfidence")
    if isinstance(claim_confidence, (int, float)):
        return max(0, min(100, round(claim_confidence * 100)))

    return None


# ---------------------------------------------------------------------------
# Test 1: compute_reliability_score — uses highest risk field
# ---------------------------------------------------------------------------
def test_compute_reliability_score_uses_highest_risk_field():
    score = compute_reliability_score(
        {
            "misleadingProbability": 0.2,
            "visualAuthenticityRisk": 0.7,
            "thumbnailClickbaitScore": 0.1,
            "repostRisk": 0.4,
        }
    )
    assert score == 30


# ---------------------------------------------------------------------------
# Test 2: compute_reliability_score — falls back to claim confidence
# ---------------------------------------------------------------------------
def test_compute_reliability_score_falls_back_to_claim_confidence():
    score = compute_reliability_score({"claimConfidence": 0.85})
    assert score == 85


# ---------------------------------------------------------------------------
# Test 3: compute_reliability_score — empty result returns None
# ---------------------------------------------------------------------------
def test_compute_reliability_score_returns_none_for_empty_result():
    assert compute_reliability_score(None) is None
    assert compute_reliability_score({}) is None
