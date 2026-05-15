from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, Enum as SqlEnum, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from storage.core.config import settings


class Base(DeclarativeBase):
    pass


class Platform(str, enum.Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    X = "x"
    FACEBOOK = "facebook"
    DIRECT_UPLOAD = "direct_upload"
    UNKNOWN = "unknown"


class Video(Base):
    """A completed RealReel analysis for one submitted video."""

    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    original_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    platform: Mapped[Platform] = mapped_column(
        SqlEnum(
            Platform,
            name="video_platform",
            values_callable=lambda enum_class: [member.value for member in enum_class],
        ),
        nullable=False,
        default=Platform.UNKNOWN,
    )

    title: Mapped[str | None] = mapped_column(Text)
    uploader_handle: Mapped[str | None] = mapped_column(String(255))
    uploader_url: Mapped[str | None] = mapped_column(Text)

    raw_video_path: Mapped[str | None] = mapped_column(Text)
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    transcript_path: Mapped[str | None] = mapped_column(Text)
    transcript_text: Mapped[str | None] = mapped_column(Text)

    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    file_sha256: Mapped[str | None] = mapped_column(String(64), unique=True)

    video_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dimension),
    )
    embedding_model: Mapped[str | None] = mapped_column(String(128))

    ai_generated_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    misleading_context_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    repost_probability: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    credibility_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    overall_risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    reasons: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("ai_generated_score >= 0 and ai_generated_score <= 1"),
        CheckConstraint("misleading_context_score >= 0 and misleading_context_score <= 1"),
        CheckConstraint("repost_probability >= 0 and repost_probability <= 1"),
        CheckConstraint("credibility_score >= 0 and credibility_score <= 1"),
        CheckConstraint("overall_risk_score >= 0 and overall_risk_score <= 1"),
        CheckConstraint("confidence >= 0 and confidence <= 1"),
        Index("ix_videos_platform", "platform"),
        Index("ix_videos_created_at", "created_at"),
        Index("ix_videos_file_sha256", "file_sha256"),
    )
