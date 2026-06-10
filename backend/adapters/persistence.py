from __future__ import annotations

from typing import Any

from pipeline.config import DATABASE_SAVE_ENABLED
from storage.services.db_videos import (
    build_db_video_payload,
    persist_db_video_sync,
)


def persist_analysis_record(
    *,
    original_url: str,
    platform: str,
    file_sha256: str,
    download_info: dict,
    transcript: dict,
    raw_video_storage_path: str | None,
    thumbnail_storage_path: str | None,
    transcript_storage_path: str,
    claim_analysis: dict,
    thumbnail_clickbait_analysis: dict,
    metadata_analysis: dict,
    repost_result: dict,
    repost_risk: float | None,
    analysis_paths: dict[str, str | None],
) -> dict[str, Any]:
    """Persist a completed analysis run through the storage layer when enabled."""
    if not DATABASE_SAVE_ENABLED:
        return {
            "ok": False,
            "videoId": None,
            "error": "Database save disabled or DATABASE_URL is not configured.",
            "skipped": True,
        }

    payload = build_db_video_payload(
        original_url=original_url,
        platform=platform,
        file_sha256=file_sha256,
        download_info=download_info,
        transcript_text=transcript.get("text"),
        raw_video_path=raw_video_storage_path,
        thumbnail_path=thumbnail_storage_path,
        transcript_path=transcript_storage_path,
        claim_analysis=claim_analysis,
        thumbnail_clickbait_analysis=thumbnail_clickbait_analysis,
        metadata_analysis=metadata_analysis,
        repost_result=repost_result,
        repost_risk=repost_risk,
        analysis_paths=analysis_paths,
    )
    return persist_db_video_sync(payload)
