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
    """Persist a completed analysis run through the storage layer when enabled.

    Args:
        original_url (str): Canonical source URL for the video.
        platform (str): Parsed platform identifier (e.g. ``youtube``, ``tiktok``).
        file_sha256 (str): SHA-256 hash of the downloaded video file.
        download_info (dict): yt-dlp metadata used for platform upload date and uploader.
        transcript (dict): Transcription payload including ``text``.
        raw_video_storage_path (str | None): Supabase path for raw video, if uploaded.
        thumbnail_storage_path (str | None): Supabase path for thumbnail, if available.
        transcript_storage_path (str): Supabase path for the transcript JSON.
        claim_analysis (dict): Normalized claim-analysis result from the pipeline.
        thumbnail_clickbait_analysis (dict): Thumbnail clickbait analysis result.
        metadata_analysis (dict): Metadata rule-analysis result.
        repost_result (dict): Repost assessment JSON (``isRepost``, ``matches``, etc.).
        repost_risk (float | None): Normalized repost risk score in 0.0–1.0.
        analysis_paths (dict[str, str | None]): Storage paths for all analysis artifacts.

    Returns:
        dict[str, Any]: ``{"ok": true, "videoId": "<uuid>", "error": null}`` on success.
        ``{"ok": false, "videoId": null, "error": "<reason>", "skipped": true}`` when
        ``DATABASE_URL`` is missing or database save is disabled. On Postgres failure,
        ``{"ok": false, "videoId": null, "error": "<reason>"}`` while analysis output
        is preserved upstream.
    """
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
