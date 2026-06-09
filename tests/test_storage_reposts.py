import os
import sys
import types
import importlib.util
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
os.environ.setdefault("EMBEDDING_DIMENSION", "512")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sqlalchemy_module = types.ModuleType("sqlalchemy")
sqlalchemy_module.select = lambda *args, **kwargs: None
sqlalchemy_ext_module = types.ModuleType("sqlalchemy.ext")
sqlalchemy_asyncio_module = types.ModuleType("sqlalchemy.ext.asyncio")
sqlalchemy_asyncio_module.AsyncSession = object

storage_module = types.ModuleType("storage")
storage_module.__path__ = []
storage_db_module = types.ModuleType("storage.db")
storage_models_module = types.ModuleType("storage.db.models")
storage_vector_module = types.ModuleType("storage.vector")


class FakeVideo:
    file_sha256 = object()
    id = object()


storage_models_module.Video = FakeVideo


async def fake_find_similar_videos(*args, **kwargs):
    return []


storage_vector_module.find_similar_videos = fake_find_similar_videos

sys.modules.setdefault("sqlalchemy", sqlalchemy_module)
sys.modules.setdefault("sqlalchemy.ext", sqlalchemy_ext_module)
sys.modules.setdefault("sqlalchemy.ext.asyncio", sqlalchemy_asyncio_module)
sys.modules.setdefault("storage", storage_module)
sys.modules.setdefault("storage.db", storage_db_module)
sys.modules.setdefault("storage.db.models", storage_models_module)
sys.modules.setdefault("storage.vector", storage_vector_module)

spec = importlib.util.spec_from_file_location(
    "reposts_under_test",
    PROJECT_ROOT / "storage" / "services" / "reposts.py",
)
assert spec is not None and spec.loader is not None
reposts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reposts)


class RepostScoringTests(unittest.TestCase):
    def test_probability_from_distance_uses_expected_thresholds(self) -> None:
        self.assertEqual(reposts._probability_from_distance(0.01), Decimal("0.9800"))
        self.assertEqual(reposts._probability_from_distance(0.05), Decimal("0.9200"))
        self.assertEqual(reposts._probability_from_distance(0.12), Decimal("0.8200"))
        self.assertEqual(reposts._probability_from_distance(0.19), Decimal("0.5500"))

    def test_serialize_match_converts_database_values_to_api_safe_types(self) -> None:
        created_at = datetime(2026, 6, 8, 12, 30, tzinfo=timezone.utc)
        serialized = reposts._serialize_match(
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "original_url": "https://example.com/source.mp4",
                "platform": "direct",
                "title": "Original clip",
                "thumbnail_path": "videos/source/thumb.jpg",
                "created_at": created_at,
                "overall_risk_score": Decimal("0.42"),
                "similarity": Decimal("0.91"),
                "distance": Decimal("0.09"),
            }
        )

        self.assertEqual(serialized["createdAt"], "2026-06-08T12:30:00+00:00")
        self.assertEqual(serialized["overallRiskScore"], 0.42)
        self.assertEqual(serialized["similarity"], 0.91)
        self.assertEqual(serialized["distance"], 0.09)

    def test_apply_repost_assessment_preserves_higher_existing_probability(self) -> None:
        payload = {
            "repost_probability": Decimal("0.7000"),
            "misleading_context_score": Decimal("0.1000"),
            "overall_risk_score": Decimal("0.2000"),
            "reasons": {"flags": ["manual_review"]},
        }
        assessment = {
            "isRepost": False,
            "repostProbability": Decimal("0.5500"),
            "matches": [],
            "rationale": "Close but outside the repost threshold.",
        }

        merged = reposts.apply_repost_assessment_to_payload(payload, assessment)

        self.assertEqual(merged["repost_probability"], Decimal("0.7000"))
        self.assertEqual(merged["misleading_context_score"], Decimal("0.1000"))
        self.assertEqual(merged["overall_risk_score"], Decimal("0.2000"))
        self.assertEqual(merged["reasons"]["flags"], ["manual_review"])
        self.assertEqual(merged["reasons"]["repost"]["repostProbability"], 0.55)

    def test_apply_repost_assessment_adds_flag_once_for_repost(self) -> None:
        payload = {
            "repost_probability": Decimal("0.1000"),
            "misleading_context_score": Decimal("0.2000"),
            "overall_risk_score": Decimal("0.3000"),
            "reasons": {"flags": ["possible_repost"]},
        }
        assessment = {
            "isRepost": True,
            "repostProbability": Decimal("0.9800"),
            "matches": [{"similarity": 0.99}],
            "rationale": "Exact or near-exact match.",
        }

        merged = reposts.apply_repost_assessment_to_payload(payload, assessment)

        self.assertEqual(merged["repost_probability"], Decimal("0.9800"))
        self.assertEqual(merged["misleading_context_score"], Decimal("0.6500"))
        self.assertEqual(merged["overall_risk_score"], Decimal("0.6500"))
        self.assertEqual(merged["reasons"]["flags"], ["possible_repost"])
        self.assertIn("Reused footage", merged["reasons"]["misleadingContext"])


if __name__ == "__main__":
    unittest.main()
