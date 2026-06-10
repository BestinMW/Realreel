from __future__ import annotations

from pipeline.config import REPOST_ASSESSMENT_ENABLED
from storage.services.reposts import (
    extract_repost_match_date,
    json_safe_assessment,
    repost_risk_score,
    run_repost_assessment_sync,
)


def assess_repost_history(
    file_sha256: str,
    *,
    original_url: str,
    download_info: dict,
) -> tuple[dict, str | None, dict, float | None]:
    """Run repost assessment through the storage layer when enabled."""
    if not REPOST_ASSESSMENT_ENABLED:
        skipped = {
            "isRepost": False,
            "repostProbability": None,
            "matches": [],
            "rationale": "Repost assessment disabled or DATABASE_URL is not configured.",
            "skipped": True,
            "skipReason": "Repost assessment disabled or DATABASE_URL is not configured.",
        }
        return skipped, None, skipped, None

    assessment = run_repost_assessment_sync(
        file_sha256=file_sha256,
        embedding=None,
        original_url=original_url,
        uploader_handle=download_info.get("uploader_id") or download_info.get("channel"),
        upload_date=download_info.get("upload_date"),
    )
    result = json_safe_assessment(assessment)
    return (
        assessment,
        extract_repost_match_date(assessment),
        result,
        repost_risk_score(assessment),
    )
