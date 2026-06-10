from __future__ import annotations

from decimal import Decimal
from typing import Any

from storage.db.models import Platform
from storage.db.sync_bridge import run_db_coroutine
from storage.schemas import VideoCreate
from storage.services.reposts import parse_platform_upload_date

_PLATFORM_MAP = {
    "youtube": Platform.YOUTUBE,
    "tiktok": Platform.TIKTOK,
    "instagram": Platform.INSTAGRAM,
    "x": Platform.X,
    "facebook": Platform.FACEBOOK,
    "direct": Platform.DIRECT_UPLOAD,
    "direct_upload": Platform.DIRECT_UPLOAD,
}

def _risk(value: Any) -> float | None:
    if isinstance(value, (int, float)) and value == value:
        return max(0.0, min(1.0, float(value)))
    return None


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 4)))


def compute_overall_risk_score(
    *,
    misleading_probability: Any = None,
    visual_authenticity_risk: Any = None,
    thumbnail_clickbait_score: Any = None,
    repost_risk: Any = None,
) -> float:
    risks = [
        score
        for score in (
            _risk(misleading_probability),
            _risk(visual_authenticity_risk),
            _risk(thumbnail_clickbait_score),
            _risk(repost_risk),
        )
        if score is not None
    ]
    return max(risks) if risks else 0.0


def build_db_video_payload(
    *,
    original_url: str,
    platform: str,
    file_sha256: str,
    download_info: dict[str, Any],
    transcript_text: str | None,
    raw_video_path: str | None,
    thumbnail_path: str | None,
    transcript_path: str | None,
    claim_analysis: dict[str, Any],
    thumbnail_clickbait_analysis: dict[str, Any],
    metadata_analysis: dict[str, Any],
    repost_result: dict[str, Any],
    repost_risk: float | None,
    analysis_paths: dict[str, str | None],
) -> VideoCreate:
    """Map a completed analysis run into a ``VideoCreate`` payload for Postgres.

    Args:
        original_url (str): Submitted video URL.
        platform (str): Platform slug (e.g. ``youtube``, ``tiktok``).
        file_sha256 (str): SHA-256 hash of the downloaded video file.
        download_info (dict[str, Any]): yt-dlp metadata (title, duration, upload_date, etc.).
        transcript_text (str | None): Truncated transcript excerpt.
        raw_video_path (str | None): Supabase path for the raw video artifact.
        thumbnail_path (str | None): Supabase path for the thumbnail artifact.
        transcript_path (str | None): Supabase path for the transcript JSON artifact.
        claim_analysis (dict[str, Any]): Claim and risk fields from the engine.
        thumbnail_clickbait_analysis (dict[str, Any]): Thumbnail clickbait analysis output.
        metadata_analysis (dict[str, Any]): Metadata rule analysis output.
        repost_result (dict[str, Any]): Repost assessment from storage.
        repost_risk (float | None): Computed repost risk score, if available.
        analysis_paths (dict[str, str | None]): Storage paths for analysis JSON artifacts.

    Returns:
        VideoCreate: Pydantic payload with scores (``ai_generated_score``,
        ``misleading_context_score``, ``repost_probability``, ``overall_risk_score``,
        ``credibility_score``, ``confidence``) and a ``reasons`` JSON object suitable
        for ``persist_analyzed_video`` / ``persist_db_video_sync``.
    """
    misleading = _risk(claim_analysis.get("misleadingProbability")) or 0.0
    visual = _risk(claim_analysis.get("visualAuthenticityRisk")) or 0.0
    thumbnail = _risk(thumbnail_clickbait_analysis.get("clickbaitScore"))
    repost = _risk(repost_risk)
    if repost is None:
        repost = _risk(repost_result.get("repostProbability")) or 0.0

    overall_risk = compute_overall_risk_score(
        misleading_probability=misleading,
        visual_authenticity_risk=visual,
        thumbnail_clickbait_score=thumbnail,
        repost_risk=repost,
    )
    confidence = _risk(claim_analysis.get("confidence")) or 0.5

    duration = download_info.get("duration")
    duration_seconds = None
    if isinstance(duration, (int, float)):
        duration_seconds = Decimal(str(round(float(duration), 3)))

    reasons: dict[str, Any] = {
        "platform": {
            "uploadDate": download_info.get("upload_date"),
        },
        "claim": {
            "verdict": claim_analysis.get("verdict"),
            "summary": claim_analysis.get("summary"),
            "recommendedAction": claim_analysis.get("recommendedAction"),
        },
        "scores": {
            "misleadingProbability": misleading,
            "visualAuthenticityRisk": visual,
            "thumbnailClickbaitScore": thumbnail,
            "repostRisk": repost,
            "metadataScore": metadata_analysis.get("metadata_score"),
            "overallRiskScore": overall_risk,
            "reliabilityScore": round((1 - overall_risk) * 100),
        },
        "analysisPaths": analysis_paths,
    }
    if repost_result and not repost_result.get("skipped"):
        reasons["repost"] = repost_result

    return VideoCreate(
        original_url=original_url,
        platform=_PLATFORM_MAP.get(platform.lower(), Platform.UNKNOWN),
        title=download_info.get("title"),
        uploader_handle=download_info.get("uploader_id") or download_info.get("channel"),
        uploader_url=download_info.get("uploader_url") or download_info.get("channel_url"),
        raw_video_path=raw_video_path,
        thumbnail_path=thumbnail_path,
        transcript_path=transcript_path,
        transcript_text=(transcript_text or "")[:20000] or None,
        duration_seconds=duration_seconds,
        platform_upload_date=parse_platform_upload_date(download_info.get("upload_date")),
        file_sha256=file_sha256,
        video_embedding=None,
        embedding_model=None,
        ai_generated_score=_decimal(visual),
        misleading_context_score=_decimal(misleading),
        repost_probability=_decimal(repost),
        credibility_score=_decimal(max(0.0, 1.0 - overall_risk)),
        overall_risk_score=_decimal(overall_risk),
        confidence=_decimal(confidence),
        reasons=reasons,
    )


def persist_db_video_sync(payload: VideoCreate) -> dict[str, Any]:
    """Insert or update one row in ``public.videos`` from a completed analysis payload.

    Args:
        payload (VideoCreate): Completed analysis row (``original_url``, ``file_sha256``,
            risk scores, ``reasons``, artifact paths, etc.).

    Returns:
        dict[str, Any]: On success,
        ``{"ok": True, "videoId": "<uuid>", "error": None}``. On failure,
        ``{"ok": False, "videoId": None, "error": "<message>"}`` (storage unavailable,
        connection error, or missing ``DATABASE_URL``). Does not raise when the database
        is disabled; callers surface ``databaseSaveOk: false`` in the streamed result.
    """
    try:
        return run_db_coroutine(_persist_db_video_async(payload))
    except Exception as exc:
        return {
            "ok": False,
            "videoId": None,
            "error": str(exc),
        }


async def _persist_db_video_async(payload: VideoCreate) -> dict[str, Any]:
    """Persist one ``VideoCreate`` row inside a bridge database session.

    Args:
        payload (VideoCreate): Completed analysis row to upsert.

    Returns:
        dict[str, Any]: On success,
        ``{"ok": True, "videoId": "<uuid>", "error": None}``. Raises
        ``RuntimeError`` when no database session is available.
    """
    from storage.db.sync_bridge import bridge_session
    from storage.services.videos import persist_analyzed_video

    async for session in bridge_session():
        video = await persist_analyzed_video(session, payload)
        await session.commit()
        return {
            "ok": True,
            "videoId": str(video.id),
            "error": None,
        }

    raise RuntimeError("Database session was not available.")
