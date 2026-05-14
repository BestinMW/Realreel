from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storage.assets.paths import all_asset_prefixes
from storage.assets.supabase import SupabaseStorageService, storage_service
from storage.db.models import Video
from storage.schemas import VideoCreate


async def save_analyzed_video(session: AsyncSession, payload: VideoCreate) -> Video:
    """Store one completed analysis result.

    The worker should call this only after downloading/analyzing the video has
    succeeded. In-progress state should live in the queue system.
    """
    data = payload.model_dump(mode="python")
    data["original_url"] = str(payload.original_url)
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
    storage: SupabaseStorageService = storage_service,
) -> None:
    video = await get_video_or_raise(session, video_id)
    await storage.delete_prefixes(all_asset_prefixes(video_id))
    await session.delete(video)
    await session.flush()
