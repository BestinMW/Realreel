from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from storage.core.config import settings


def validate_embedding(embedding: list[float]) -> None:
    if len(embedding) != settings.embedding_dimension:
        raise ValueError(
            f"Expected embedding dimension {settings.embedding_dimension}, "
            f"got {len(embedding)}."
        )


async def find_similar_videos(
    session: AsyncSession,
    *,
    embedding: list[float],
    limit: int = 10,
    max_cosine_distance: float = 0.2,
    exclude_video_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """Find previously analyzed videos similar to a new whole-video embedding."""
    validate_embedding(embedding)

    query = """
        select
            v.id,
            v.original_url,
            v.platform,
            v.title,
            v.thumbnail_path,
            v.overall_risk_score,
            (v.video_embedding <=> cast(:embedding as vector)) as distance,
            1 - (v.video_embedding <=> cast(:embedding as vector)) as similarity
        from videos v
        where v.video_embedding is not null
          and (:exclude_video_id is null or v.id != :exclude_video_id)
          and (v.video_embedding <=> cast(:embedding as vector)) <= :max_distance
        order by v.video_embedding <=> cast(:embedding as vector)
        limit :limit
    """
    result = await session.execute(
        text(query),
        {
            "embedding": _vector_literal(embedding),
            "limit": limit,
            "max_distance": max_cosine_distance,
            "exclude_video_id": exclude_video_id,
        },
    )
    return [dict(row._mapping) for row in result]


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"
