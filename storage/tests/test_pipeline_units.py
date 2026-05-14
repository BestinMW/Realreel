import os
import unittest
import uuid
from decimal import Decimal


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
os.environ.setdefault("EMBEDDING_DIMENSION", "512")

from storage.assets.paths import (  # noqa: E402
    raw_video_path,
    thumbnail_path,
    transcript_path,
)
from storage.db.models import Platform  # noqa: E402
from storage.schemas import VideoCreate  # noqa: E402
from storage.vector import validate_embedding  # noqa: E402


class StoragePipelineUnitTests(unittest.TestCase):
    def test_video_payload_validates(self) -> None:
        payload = VideoCreate(
            original_url="https://www.youtube.com/watch?v=test-video",
            platform=Platform.YOUTUBE,
            title="Test video",
            raw_video_path="videos/test/raw/original.mp4",
            thumbnail_path="videos/test/thumbnails/thumbnail.jpg",
            transcript_text="This is a test transcript.",
            duration_seconds=Decimal("12.5"),
            file_sha256="a" * 64,
            video_embedding=[0.01] * 512,
            embedding_model="test-embedding-model",
            ai_generated_score=Decimal("0.1000"),
            misleading_context_score=Decimal("0.2000"),
            repost_probability=Decimal("0.3000"),
            credibility_score=Decimal("0.8000"),
            overall_risk_score=Decimal("0.2500"),
            confidence=Decimal("0.9000"),
            reasons={"summary": "Unit test payload."},
        )

        self.assertEqual(payload.platform, Platform.YOUTUBE)
        self.assertEqual(len(payload.video_embedding or []), 512)

    def test_storage_paths_are_deterministic(self) -> None:
        video_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        self.assertEqual(
            raw_video_path(video_id, "clip.mp4"),
            "videos/00000000-0000-0000-0000-000000000001/raw/original.mp4",
        )
        self.assertEqual(
            thumbnail_path(video_id),
            "videos/00000000-0000-0000-0000-000000000001/thumbnails/thumbnail.jpg",
        )
        self.assertEqual(
            transcript_path(video_id, "en"),
            "videos/00000000-0000-0000-0000-000000000001/transcripts/transcript-en.json",
        )

    def test_embedding_dimension_is_checked(self) -> None:
        validate_embedding([0.0] * 512)

        with self.assertRaises(ValueError):
            validate_embedding([0.0] * 3)


if __name__ == "__main__":
    unittest.main()
