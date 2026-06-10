"""Unit tests for repost helper functions used by the engine layer.

Run:
    pytest tests/engine/test_repost.py -v
"""

import tempfile
from decimal import Decimal
from pathlib import Path

from pipeline.media import compute_file_sha256
from storage.services.reposts import extract_repost_match_date, repost_risk_score


# ---------------------------------------------------------------------------
# Test 1: compute_file_sha256 — stable hash for the same file
# ---------------------------------------------------------------------------
def test_compute_file_sha256_is_stable_for_same_file():
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        handle.write(b"realreel-repost-test")
        temp_path = Path(handle.name)

    try:
        assert compute_file_sha256(temp_path) == compute_file_sha256(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 2: extract_repost_match_date — reads platform upload date
# ---------------------------------------------------------------------------
def test_extract_repost_match_date_reads_platform_upload_date():
    assessment = {"matches": [{"platformUploadDate": "2023-01-15"}]}
    assert extract_repost_match_date(assessment) == "20230115"


# ---------------------------------------------------------------------------
# Test 3: repost_risk_score — floors confirmed reposts
# ---------------------------------------------------------------------------
def test_repost_risk_score_floors_confirmed_reposts():
    assert repost_risk_score(
        {"isRepost": True, "repostProbability": Decimal("0.8200")}
    ) == 0.82
    assert repost_risk_score(
        {"isRepost": True, "repostProbability": Decimal("0.4000")}
    ) == 0.65


# ---------------------------------------------------------------------------
# Test 4: repost_risk_score — ignores clean no-match results
# ---------------------------------------------------------------------------
def test_repost_risk_score_ignores_clean_no_match_results():
    assert (
        repost_risk_score(
            {"isRepost": False, "repostProbability": Decimal("0.0000")}
        )
        is None
    )
