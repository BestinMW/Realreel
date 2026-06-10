from __future__ import annotations

import uuid
from datetime import date, datetime
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
    platform_upload_date: date | None = None
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


class FeedbackCreate(BaseModel):
    vid_id: str = Field(min_length=1)
    label: str
    comment: str | None = None
