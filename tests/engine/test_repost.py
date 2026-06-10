"""Unit tests for repost helper functions used by the engine layer.

Run:
    pytest tests/engine/test_repost.py -v
"""

import tempfile
from decimal import Decimal
from pathlib import Path

from pipeline.media import compute_file_sha256
from storage.services.reposts import (
    extract_repost_match_date,
    json_safe_assessment,
    repost_risk_score,
)


# ---------------------------------------------------------------------------
# compute_file_sha256
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
# extract_repost_match_date
# ---------------------------------------------------------------------------
def test_extract_repost_match_date_reads_and_rejects_bad_values():
    assert extract_repost_match_date(
        {"matches": [{"platformUploadDate": "2023-01-15"}]}
    ) == "20230115"
    assert extract_repost_match_date({"matches": []}) is None
    assert (
        extract_repost_match_date(
            {"matches": [{"platformUploadDate": "not-a-date"}]}
        )
        is None
    )


# ---------------------------------------------------------------------------
# repost_risk_score
# ---------------------------------------------------------------------------
def test_repost_risk_score_maps_assessment_to_pipeline_risk():
    assert repost_risk_score(
        {"isRepost": True, "repostProbability": Decimal("0.8200")}
    ) == 0.82
    assert repost_risk_score(
        {"isRepost": True, "repostProbability": Decimal("0.4000")}
    ) == 0.65
    assert repost_risk_score({"isRepost": True, "repostProbability": None}) == 0.65
    assert repost_risk_score({"skipped": True, "isRepost": True}) is None
    assert (
        repost_risk_score(
            {"isRepost": False, "repostProbability": Decimal("0.0000")}
        )
        is None
    )


# ---------------------------------------------------------------------------
# json_safe_assessment
# ---------------------------------------------------------------------------
def test_json_safe_assessment_converts_decimal_probability_to_float():
    safe = json_safe_assessment(
        {"isRepost": True, "repostProbability": Decimal("0.8200")}
    )

    assert safe["repostProbability"] == 0.82
    assert isinstance(safe["repostProbability"], float)
