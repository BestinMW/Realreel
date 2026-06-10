from __future__ import annotations

from typing import Any

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storage.db.models import Video
from storage.schemas import VideoCreate


async def persist_analyzed_video(session: AsyncSession, payload: VideoCreate) -> Video:
    """Store a pipeline result without re-running repost detection.

    Args:
        session (AsyncSession): Active SQLAlchemy async database session.
        payload (VideoCreate): Completed analysis row built by ``build_db_video_payload``.

    Returns:
        Video: The inserted or updated ORM row whose ``id`` is returned as ``videoId`` in
        ``{"ok": True, "videoId": "<uuid>", "error": None}`` from ``persist_db_video_sync``.
        When Postgres is unavailable, the engine preserves the analysis result and reports
        ``databaseSaveOk: false`` in the streamed ``complete`` event.
    """
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


async def find_video_by_url(session: AsyncSession, original_url: str) -> Video | None:
    """Look up a saved video by its original submission URL.

    Args:
        session (AsyncSession): Active SQLAlchemy async database session.
        original_url (str): Submitted video URL used as the upsert key during persistence.

    Returns:
        Video | None: The matching ORM row, or ``None`` when no prior analysis exists for the
        URL.
    """
    result = await session.execute(
        select(Video).where(Video.original_url == original_url).limit(1)
    )
    return result.scalar_one_or_none()
