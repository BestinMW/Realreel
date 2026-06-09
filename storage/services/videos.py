from __future__ import annotations

from typing import Any

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storage.assets.paths import all_asset_prefixes
from storage.db.models import Video
from storage.schemas import VideoCreate
from storage.services.reposts import (
    apply_repost_assessment_to_payload,
    assess_repost_risk,
)


async def save_analyzed_video(session: AsyncSession, payload: VideoCreate) -> Video:
    """Store one completed analysis result and run repost detection on save."""
    data = payload.model_dump(mode="python")
    data["original_url"] = str(payload.original_url)
    repost_assessment = await assess_repost_risk(
        session,
        embedding=payload.video_embedding,
        file_sha256=payload.file_sha256,
    )
    data = apply_repost_assessment_to_payload(data, repost_assessment)
    return await _insert_or_update_video(session, data)


async def persist_analyzed_video(session: AsyncSession, payload: VideoCreate) -> Video:
    """Store a pipeline result without re-running repost detection."""
    data = payload.model_dump(mode="python")
    data["original_url"] = str(payload.original_url)
    return await _insert_or_update_video(session, data)


async def _insert_or_update_video(session: AsyncSession, data: dict[str, Any]) -> Video:
    existing = await find_video_by_url(session, data["original_url"])
    if existing is not None:
        for key, value in data.items():
            setattr(existing, key, value)
        await session.flush()
        return existing

    video = Video(**data)
    session.add(video)
    await session.flush()
    return video


async def get_video_or_raise(session: AsyncSession, video_id: uuid.UUID) -> Video:
    video = await session.get(Video, video_id)

    if video is None:
        raise LookupError(f"Video not found: {video_id}")

    return video


async def find_video_by_url(session: AsyncSession, original_url: str) -> Video | None:
    result = await session.execute(
        select(Video).where(Video.original_url == original_url).limit(1)
    )
    return result.scalar_one_or_none()


async def find_video_by_sha256(session: AsyncSession, file_sha256: str) -> Video | None:
    result = await session.execute(
        select(Video).where(Video.file_sha256 == file_sha256).limit(1)
    )
    return result.scalar_one_or_none()


async def list_recent_videos(session: AsyncSession, limit: int = 25) -> list[Video]:
    result = await session.execute(
        select(Video).order_by(Video.created_at.desc()).limit(limit)
    )
    return list(result.scalars())


async def delete_video_and_assets(
    session: AsyncSession,
    *,
    video_id: uuid.UUID,
    storage=None,
) -> None:
    if storage is None:
        from storage.assets.supabase import storage_service

        storage = storage_service

    video = await get_video_or_raise(session, video_id)
    await storage.delete_prefixes(all_asset_prefixes(video_id))
    await session.delete(video)
    await session.flush()
