from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storage.db.models import Video
from storage.db.sync_bridge import run_db_coroutine
from storage.vector import find_similar_videos

REPOST_DISTANCE_THRESHOLD = 0.12
POSSIBLE_REPOST_DISTANCE_THRESHOLD = 0.2


class VideoPostContext(NamedTuple):
    original_url: str | None
    uploader_handle: str | None
    upload_date: date | None


def parse_platform_upload_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").date()
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _norm_url(url: str | None) -> str:
    return (url or "").strip().rstrip("/").lower()


def _norm_uploader(handle: str | None) -> str:
    return (handle or "").strip().lstrip("@").lower()


def _legacy_upload_date_from_reasons(reasons: Any) -> date | None:
    if isinstance(reasons, dict) and isinstance(reasons.get("platform"), dict):
        return parse_platform_upload_date(reasons["platform"].get("uploadDate"))
    return None


def _resolve_upload_date(source: Video | dict[str, Any]) -> date | None:
    if isinstance(source, Video):
        return source.platform_upload_date or _legacy_upload_date_from_reasons(source.reasons)
    return (
        parse_platform_upload_date(source.get("platform_upload_date"))
        or _legacy_upload_date_from_reasons(source.get("reasons"))
    )


def _post_context(source: Video | dict[str, Any]) -> VideoPostContext:
    if isinstance(source, Video):
        return VideoPostContext(
            source.original_url,
            source.uploader_handle,
            _resolve_upload_date(source),
        )
    return VideoPostContext(
        source.get("original_url"),
        source.get("uploader_handle"),
        _resolve_upload_date(source),
    )


def _is_different_post(current: VideoPostContext, matched: VideoPostContext) -> bool:
    if _norm_url(current.original_url) == _norm_url(matched.original_url):
        return False
    same_author = (
        _norm_uploader(current.uploader_handle)
        and _norm_uploader(current.uploader_handle) == _norm_uploader(matched.uploader_handle)
    )
    if same_author and current.upload_date and matched.upload_date and current.upload_date == matched.upload_date:
        return False
    diff_author = (
        _norm_uploader(current.uploader_handle)
        and _norm_uploader(matched.uploader_handle)
        and _norm_uploader(current.uploader_handle) != _norm_uploader(matched.uploader_handle)
    )
    diff_date = (
        current.upload_date is not None
        and matched.upload_date is not None
        and current.upload_date != matched.upload_date
    )
    return diff_author or diff_date


def _should_flag_repost(
    current: VideoPostContext,
    matched: VideoPostContext,
) -> tuple[bool, str]:
    if not _is_different_post(current, matched):
        return False, "Matches a previously analyzed post from the same source."
    if not (
        current.upload_date
        and matched.upload_date
        and current.upload_date > matched.upload_date
    ):
        return False, "Current post date is not later than the matched previously analyzed video."
    if (
        _norm_uploader(current.uploader_handle)
        and _norm_uploader(matched.uploader_handle)
        and _norm_uploader(current.uploader_handle) != _norm_uploader(matched.uploader_handle)
    ):
        return True, "Same footage appears in a later post from a different author."
    return True, "Same footage appears in a later post with a different publish date."


def _probability_from_distance(distance: float) -> Decimal:
    if distance <= 0.02:
        return Decimal("0.9800")
    if distance <= 0.06:
        return Decimal("0.9200")
    if distance <= REPOST_DISTANCE_THRESHOLD:
        return Decimal("0.8200")
    return Decimal("0.5500")


def _serialize_match(match: dict[str, Any]) -> dict[str, Any]:
    ctx = _post_context(match)
    created_at = match.get("created_at")
    risk = match.get("overall_risk_score")
    return {
        "id": str(match.get("id")),
        "originalUrl": match.get("original_url"),
        "platform": match.get("platform"),
        "title": match.get("title"),
        "uploaderHandle": match.get("uploader_handle"),
        "platformUploadDate": ctx.upload_date.isoformat() if ctx.upload_date else None,
        "thumbnailPath": match.get("thumbnail_path"),
        "createdAt": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "overallRiskScore": float(risk) if risk is not None else None,
        "similarity": float(match["similarity"]),
        "distance": float(match["distance"]),
    }


def _assessment(
    *,
    flagged: bool,
    probability: Decimal | None,
    matches: list[dict[str, Any]],
    rationale: str,
    confirmed: bool = False,
) -> dict[str, Any]:
    return {
        "isRepost": flagged and confirmed,
        "repostProbability": probability if flagged else Decimal("0.0000") if probability is not None else None,
        "matches": matches,
        "rationale": rationale,
    }


async def assess_repost_risk(
    session: AsyncSession,
    *,
    embedding: list[float] | None,
    file_sha256: str | None = None,
    exclude_video_id: uuid.UUID | None = None,
    original_url: str | None = None,
    uploader_handle: str | None = None,
    upload_date: str | date | datetime | None = None,
) -> dict[str, Any]:
    """Compare a submitted video with saved videos and explain repost risk.

    Args:
        session (AsyncSession): Active SQLAlchemy async database session.
        embedding (list[float] | None): Optional whole-video embedding for similarity search.
        file_sha256 (str | None): SHA-256 hash for exact duplicate detection.
        exclude_video_id (uuid.UUID | None): Video id to exclude from matches.
        original_url (str | None): Submitted video URL.
        uploader_handle (str | None): Channel or author handle.
        upload_date (str | date | datetime | None): Platform publish date for repost rules.

    Returns:
        dict[str, Any]: Assessment with ``isRepost``, ``repostProbability``, ``matches``,
        and ``rationale`` for the streamed ``complete`` result (``repostRisk``,
        ``repostMatches``, ``repostRationale``). When no prior records exist, repost risk
        remains low or unknown. When ``DATABASE_URL`` is disabled, callers receive a
        skipped assessment instead of raising.
    """
    current = VideoPostContext(
        original_url, uploader_handle, parse_platform_upload_date(upload_date)
    )

    exact = await _find_exact_hash_match(
        session,
        file_sha256=file_sha256,
        exclude_video_id=exclude_video_id,
        original_url=original_url,
    )
    if exact is not None:
        flagged, detail = _should_flag_repost(current, _post_context(exact))
        prefix = "This file has the same SHA-256 hash as a previously analyzed video."
        return _assessment(
            flagged=flagged,
            probability=Decimal("1.0000") if flagged else Decimal("0.0000"),
            matches=[_serialize_match(exact)],
            rationale=f"{prefix} {detail}",
            confirmed=True,
        )

    if not embedding:
        return _assessment(
            flagged=False,
            probability=None,
            matches=[],
            rationale="No video embedding was available for repost comparison.",
        )

    matches = await find_similar_videos(
        session,
        embedding=embedding,
        limit=5,
        max_cosine_distance=POSSIBLE_REPOST_DISTANCE_THRESHOLD,
        exclude_video_id=exclude_video_id,
        exclude_original_url=original_url,
    )
    if not matches:
        return _assessment(
            flagged=False,
            probability=Decimal("0.0000"),
            matches=[],
            rationale="No similar previously analyzed videos were found.",
        )

    serialized = [_serialize_match(match) for match in matches]
    for match in matches:
        flagged, detail = _should_flag_repost(current, _post_context(match))
        if not flagged:
            continue
        distance = float(match["distance"])
        similarity = round(float(match["similarity"]) * 100)
        return _assessment(
            flagged=True,
            probability=_probability_from_distance(distance),
            matches=serialized,
            rationale=f"{detail} Closest saved video is {similarity}% similar.",
            confirmed=distance <= REPOST_DISTANCE_THRESHOLD,
        )

    _, detail = _should_flag_repost(current, _post_context(matches[0]))
    return _assessment(
        flagged=False,
        probability=Decimal("0.0000"),
        matches=serialized,
        rationale=(
            "Similar previously analyzed footage was found, but it does not count as a "
            f"repost under the current rules. {detail}"
        ),
    )


def run_repost_assessment_sync(
    *,
    file_sha256: str | None,
    embedding: list[float] | None = None,
    original_url: str | None = None,
    uploader_handle: str | None = None,
    upload_date: str | date | datetime | None = None,
) -> dict[str, Any]:
    """Run repost assessment from synchronous callers such as the analysis pipeline.

    Args:
        file_sha256 (str | None): SHA-256 hash of the downloaded video file.
        embedding (list[float] | None): Optional whole-video embedding for similarity search.
        original_url (str | None): Submitted video URL.
        uploader_handle (str | None): Channel or author handle from platform metadata.
        upload_date (str | date | datetime | None): Platform publish date for repost rules.

    Returns:
        dict[str, Any]: Repost assessment with ``isRepost``, ``repostProbability``,
        ``matches``, and ``rationale`` for inclusion in the streamed ``complete`` result.
        On database failure, returns a skipped assessment with ``skipped: True`` and
        ``skipReason`` (repost history unavailable when ``DATABASE_URL`` is missing).
    """
    async def _run() -> dict[str, Any]:
        from storage.db.sync_bridge import bridge_session

        async for session in bridge_session():
            return await assess_repost_risk(
                session,
                embedding=embedding,
                file_sha256=file_sha256,
                original_url=original_url,
                uploader_handle=uploader_handle,
                upload_date=upload_date,
            )
        raise RuntimeError("Database session was not available.")

    try:
        return run_db_coroutine(_run())
    except Exception as exc:
        return {
            "isRepost": False,
            "repostProbability": None,
            "matches": [],
            "rationale": f"Repost assessment failed: {exc}",
            "skipped": True,
            "skipReason": str(exc),
        }


def repost_risk_score(assessment: dict[str, Any]) -> float | None:
    if assessment.get("skipped"):
        return None
    probability = assessment.get("repostProbability")
    if probability is None:
        return 0.65 if assessment.get("isRepost") else None
    value = float(probability)
    if value <= 0.0 and not assessment.get("isRepost"):
        return None
    return max(value, 0.65) if assessment.get("isRepost") else value


def extract_repost_match_date(assessment: dict[str, Any]) -> str | None:
    matches = assessment.get("matches") or []
    if not matches:
        return None
    parsed = parse_platform_upload_date(matches[0].get("platformUploadDate"))
    return parsed.strftime("%Y%m%d") if parsed else None


def apply_repost_assessment_to_payload(
    payload_data: dict[str, Any],
    assessment: dict[str, Any],
) -> dict[str, Any]:
    repost_probability = assessment.get("repostProbability")
    if repost_probability is not None:
        payload_data["repost_probability"] = max(
            Decimal(str(payload_data.get("repost_probability", "0"))),
            Decimal(str(repost_probability)),
        )
    if assessment.get("isRepost"):
        payload_data["misleading_context_score"] = max(
            Decimal(str(payload_data.get("misleading_context_score", "0"))),
            Decimal("0.6500"),
        )
        payload_data["overall_risk_score"] = max(
            Decimal(str(payload_data.get("overall_risk_score", "0"))),
            Decimal("0.6500"),
        )
    reasons = dict(payload_data.get("reasons") or {})
    reasons["repost"] = json_safe_assessment(assessment)
    if assessment.get("isRepost"):
        flags = reasons.setdefault("flags", [])
        if "possible_repost" not in flags:
            flags.append("possible_repost")
        reasons["misleadingContext"] = (
            "This video is very similar to a previously analyzed video. Reused "
            "footage can mislead viewers when it is presented as current or as "
            "evidence of a different event."
        )
    payload_data["reasons"] = reasons
    return payload_data


async def _find_exact_hash_match(
    session: AsyncSession,
    *,
    file_sha256: str | None,
    exclude_video_id: uuid.UUID | None,
    original_url: str | None = None,
) -> dict[str, Any] | None:
    if not file_sha256:
        return None
    query = select(Video).where(Video.file_sha256 == file_sha256)
    if exclude_video_id is not None:
        query = query.where(Video.id != exclude_video_id)
    if original_url:
        query = query.where(Video.original_url != original_url)
    video = (await session.execute(query.limit(1))).scalar_one_or_none()
    if video is None:
        return None
    return {
        "id": video.id,
        "original_url": video.original_url,
        "platform": video.platform.value,
        "title": video.title,
        "thumbnail_path": video.thumbnail_path,
        "uploader_handle": video.uploader_handle,
        "platform_upload_date": _resolve_upload_date(video),
        "reasons": video.reasons,
        "created_at": video.created_at,
        "overall_risk_score": video.overall_risk_score,
        "similarity": 1.0,
        "distance": 0.0,
    }


def json_safe_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    safe = dict(assessment)
    if isinstance(safe.get("repostProbability"), Decimal):
        safe["repostProbability"] = float(safe["repostProbability"])
    return safe
