from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storage.db.models import Video
from storage.vector import find_similar_videos

REPOST_DISTANCE_THRESHOLD = 0.12
POSSIBLE_REPOST_DISTANCE_THRESHOLD = 0.2


async def assess_repost_risk(
    session: AsyncSession,
    *,
    embedding: list[float] | None,
    file_sha256: str | None = None,
    exclude_video_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Compare a submitted video with saved videos and explain repost risk."""
    exact_match = await _find_exact_hash_match(
        session,
        file_sha256=file_sha256,
        exclude_video_id=exclude_video_id,
    )
    if exact_match is not None:
        return {
            "isRepost": True,
            "repostProbability": Decimal("1.0000"),
            "matches": [_serialize_match(exact_match)],
            "rationale": (
                "This file has the same SHA-256 hash as a previously analyzed "
                "video, so it is an exact repost. If the current post presents "
                "the footage as new, it may be misleading."
            ),
        }

    if not embedding:
        return {
            "isRepost": False,
            "repostProbability": None,
            "matches": [],
            "rationale": "No video embedding was available for repost comparison.",
        }

    matches = await find_similar_videos(
        session,
        embedding=embedding,
        limit=5,
        max_cosine_distance=POSSIBLE_REPOST_DISTANCE_THRESHOLD,
        exclude_video_id=exclude_video_id,
    )
    if not matches:
        return {
            "isRepost": False,
            "repostProbability": Decimal("0.0000"),
            "matches": [],
            "rationale": "No similar previously analyzed videos were found.",
        }

    best_match = matches[0]
    best_distance = float(best_match["distance"])
    best_similarity = float(best_match["similarity"])
    probability = _probability_from_distance(best_distance)
    is_repost = best_distance <= REPOST_DISTANCE_THRESHOLD

    rationale = (
        f"Closest saved video is {round(best_similarity * 100)}% similar. "
        "This may be reused footage; if the current post presents it as new, "
        "it can be more misleading because the clip may be older or from a "
        "different context."
    )

    return {
        "isRepost": is_repost,
        "repostProbability": probability,
        "matches": [_serialize_match(match) for match in matches],
        "rationale": rationale,
    }


def apply_repost_assessment_to_payload(
    payload_data: dict[str, Any],
    assessment: dict[str, Any],
) -> dict[str, Any]:
    """Merge repost assessment into the analysis payload before saving."""
    repost_probability = assessment.get("repostProbability")
    if repost_probability is not None:
        existing_probability = Decimal(str(payload_data.get("repost_probability", "0")))
        payload_data["repost_probability"] = max(
            existing_probability,
            Decimal(str(repost_probability)),
        )

    if assessment.get("isRepost"):
        misleading_score = Decimal(str(payload_data.get("misleading_context_score", "0")))
        payload_data["misleading_context_score"] = max(
            misleading_score,
            Decimal("0.6500"),
        )
        overall_score = Decimal(str(payload_data.get("overall_risk_score", "0")))
        payload_data["overall_risk_score"] = max(overall_score, Decimal("0.6500"))

    reasons = dict(payload_data.get("reasons") or {})
    reasons["repost"] = _json_safe_assessment(assessment)
    if assessment.get("isRepost"):
        reasons.setdefault("flags", [])
        if "possible_repost" not in reasons["flags"]:
            reasons["flags"].append("possible_repost")
        reasons["misleadingContext"] = (
            "This video is very similar to a previously analyzed video. Reused "
            "footage can mislead viewers when it is presented as current or as "
            "evidence of a different event."
        )
    payload_data["reasons"] = reasons
    return payload_data


def _probability_from_distance(distance: float) -> Decimal:
    if distance <= 0.02:
        return Decimal("0.9800")
    if distance <= 0.06:
        return Decimal("0.9200")
    if distance <= REPOST_DISTANCE_THRESHOLD:
        return Decimal("0.8200")
    return Decimal("0.5500")


def _serialize_match(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(match.get("id")),
        "originalUrl": match.get("original_url"),
        "platform": match.get("platform"),
        "title": match.get("title"),
        "thumbnailPath": match.get("thumbnail_path"),
        "createdAt": (
            match.get("created_at").isoformat()
            if hasattr(match.get("created_at"), "isoformat")
            else match.get("created_at")
        ),
        "overallRiskScore": (
            float(match["overall_risk_score"])
            if match.get("overall_risk_score") is not None
            else None
        ),
        "similarity": float(match["similarity"]),
        "distance": float(match["distance"]),
    }


async def _find_exact_hash_match(
    session: AsyncSession,
    *,
    file_sha256: str | None,
    exclude_video_id: uuid.UUID | None,
) -> dict[str, Any] | None:
    if not file_sha256:
        return None

    query = select(Video).where(Video.file_sha256 == file_sha256).limit(1)
    if exclude_video_id is not None:
        query = query.where(Video.id != exclude_video_id)

    result = await session.execute(query)
    video = result.scalar_one_or_none()
    if video is None:
        return None

    return {
        "id": video.id,
        "original_url": video.original_url,
        "platform": video.platform.value,
        "title": video.title,
        "thumbnail_path": video.thumbnail_path,
        "created_at": video.created_at,
        "overall_risk_score": video.overall_risk_score,
        "similarity": 1.0,
        "distance": 0.0,
    }


def _json_safe_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    safe = dict(assessment)
    probability = safe.get("repostProbability")
    if isinstance(probability, Decimal):
        safe["repostProbability"] = float(probability)
    return safe
