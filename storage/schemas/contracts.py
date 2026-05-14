from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from storage.db.models import Platform


class VideoCreate(BaseModel):
    """Payload saved after a video has already been analyzed."""

    original_url: HttpUrl
    platform: Platform = Platform.UNKNOWN
    title: str | None = None
    uploader_handle: str | None = None
    uploader_url: str | None = None

    raw_video_path: str | None = None
    thumbnail_path: str | None = None
    transcript_path: str | None = None
    transcript_text: str | None = None

    duration_seconds: Decimal | None = None
    file_sha256: str | None = None
    video_embedding: list[float] | None = None
    embedding_model: str | None = None

    ai_generated_score: Decimal
    misleading_context_score: Decimal
    repost_probability: Decimal
    credibility_score: Decimal
    overall_risk_score: Decimal
    confidence: Decimal
    reasons: dict[str, Any] = Field(default_factory=dict)


class VideoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_url: str
    platform: Platform
    title: str | None
    uploader_handle: str | None
    uploader_url: str | None
    raw_video_path: str | None
    thumbnail_path: str | None
    transcript_path: str | None
    transcript_text: str | None
    duration_seconds: Decimal | None
    file_sha256: str | None
    video_embedding: list[float] | None
    embedding_model: str | None
    ai_generated_score: Decimal
    misleading_context_score: Decimal
    repost_probability: Decimal
    credibility_score: Decimal
    overall_risk_score: Decimal
    confidence: Decimal
    reasons: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SimilarVideoQuery(BaseModel):
    embedding: list[float]
    limit: int = Field(default=10, ge=1, le=100)
    max_cosine_distance: float = Field(default=0.2, ge=0, le=2)
    exclude_video_id: uuid.UUID | None = None


class SimilarVideoRead(BaseModel):
    id: uuid.UUID
    original_url: str
    platform: Platform
    title: str | None
    thumbnail_path: str | None
    overall_risk_score: Decimal
    similarity: float
    distance: float


class AssetSignedUrlRequest(BaseModel):
    bucket: str
    storage_path: str
    expires_in: int | None = None


class SignedUrlResponse(BaseModel):
    signed_url: str
    expires_in: int
