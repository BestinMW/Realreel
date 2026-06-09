import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")

from storage.services.db_videos import (  # noqa: E402
    build_db_video_payload,
    compute_overall_risk_score,
)


class DbVideoTests(unittest.TestCase):
    def test_compute_overall_risk_score_uses_highest_input(self) -> None:
        self.assertEqual(
            compute_overall_risk_score(
                misleading_probability=0.2,
                visual_authenticity_risk=0.7,
                thumbnail_clickbait_score=0.1,
                repost_risk=0.4,
            ),
            0.7,
        )

    def test_build_db_video_payload_maps_scores_and_paths(self) -> None:
        payload = build_db_video_payload(
            original_url="https://www.youtube.com/watch?v=abc123",
            platform="youtube",
            file_sha256="a" * 64,
            download_info={
                "title": "Test video",
                "duration": 42.5,
                "uploader_id": "channel",
                "upload_date": "20240615",
            },
            transcript_text="hello world",
            raw_video_path="videos/youtube/job/raw/original.mp4",
            thumbnail_path="videos/youtube/job/thumbnails/thumbnail.jpg",
            transcript_path="videos/youtube/job/transcripts/transcript-und.json",
            claim_analysis={
                "misleadingProbability": 0.3,
                "visualAuthenticityRisk": 0.8,
                "confidence": 0.9,
                "verdict": "mixed",
                "summary": "Summary",
                "recommendedAction": "flag_for_review",
            },
            thumbnail_clickbait_analysis={"clickbaitScore": 0.25},
            metadata_analysis={"metadata_score": 0.1},
            repost_result={"isRepost": False, "repostProbability": 0.0},
            repost_risk=None,
            analysis_paths={"claimAnalysis": "videos/youtube/job/analysis/claim-analysis.json"},
        )

        self.assertEqual(payload.platform.value, "youtube")
        self.assertEqual(payload.file_sha256, "a" * 64)
        self.assertEqual(payload.ai_generated_score, Decimal("0.8000"))
        self.assertEqual(payload.misleading_context_score, Decimal("0.3000"))
        self.assertEqual(payload.overall_risk_score, Decimal("0.8000"))
        self.assertEqual(payload.credibility_score, Decimal("0.2000"))
        self.assertEqual(payload.platform_upload_date.isoformat(), "2024-06-15")
        self.assertEqual(payload.reasons["analysisPaths"]["claimAnalysis"], "videos/youtube/job/analysis/claim-analysis.json")


if __name__ == "__main__":
    unittest.main()
