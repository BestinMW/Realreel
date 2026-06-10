from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from storage.core.config import settings


def validate_embedding(embedding: list[float]) -> None:
    """Verify that an embedding vector matches the configured pgvector dimension.

    Args:
        embedding (list[float]): Whole-video embedding vector.

    Returns:
        None: When the length equals ``settings.embedding_dimension``. Raises ``ValueError``
        when the dimension does not match.
    """
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
    exclude_original_url: str | None = None,
) -> list[dict[str, Any]]:
    """Find previously analyzed videos similar to a new whole-video embedding.

    Args:
        session (AsyncSession): Active SQLAlchemy async database session.
        embedding (list[float]): Whole-video embedding used for cosine-distance search.
        limit (int): Maximum number of matches to return.
        max_cosine_distance (float): Maximum pgvector cosine distance for a candidate match.
        exclude_video_id (uuid.UUID | None): Saved video id to omit from results.
        exclude_original_url (str | None): Submission URL to omit from results.

    Returns:
        list[dict[str, Any]]: Ranked match rows with ``id``, ``original_url``, ``similarity``,
        ``distance``, and related metadata. Returns an empty list when no embeddings fall
        within the threshold (repost assessment then reports no similar videos).
    """
    validate_embedding(embedding)

    query = """
        select
            v.id,
            v.original_url,
            v.platform,
            v.title,
            v.thumbnail_path,
            v.uploader_handle,
            v.platform_upload_date,
            v.file_sha256,
            v.created_at,
            v.overall_risk_score,
            (v.video_embedding <=> cast(:embedding as vector)) as distance,
            1 - (v.video_embedding <=> cast(:embedding as vector)) as similarity
        from videos v
        where v.video_embedding is not null
          and (
            cast(:exclude_video_id as uuid) is null
            or v.id != cast(:exclude_video_id as uuid)
          )
          and (
            cast(:exclude_original_url as text) is null
            or v.original_url != cast(:exclude_original_url as text)
          )
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
            "exclude_video_id": str(exclude_video_id) if exclude_video_id else None,
            "exclude_original_url": exclude_original_url,
        },
    )
    return [dict(row._mapping) for row in result]


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"
