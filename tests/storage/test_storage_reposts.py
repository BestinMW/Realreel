"""Unit tests for repost detection rules in the storage layer.

SQLAlchemy and database calls are stubbed — these tests run without Postgres.

Run:
    pytest tests/storage/test_storage_reposts.py -v
"""

import importlib.util
import sys
import types
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

sqlalchemy_module = types.ModuleType("sqlalchemy")
sqlalchemy_module.select = lambda *args, **kwargs: None
sqlalchemy_ext_module = types.ModuleType("sqlalchemy.ext")
sqlalchemy_asyncio_module = types.ModuleType("sqlalchemy.ext.asyncio")
sqlalchemy_asyncio_module.AsyncSession = object

storage_module = types.ModuleType("storage")
storage_module.__path__ = []
storage_db_module = types.ModuleType("storage.db")
storage_db_module.__path__ = []
storage_models_module = types.ModuleType("storage.db.models")
storage_sync_bridge_module = types.ModuleType("storage.db.sync_bridge")
storage_vector_module = types.ModuleType("storage.vector")


class FakeVideo:
    file_sha256 = object()
    id = object()


storage_models_module.Video = FakeVideo


async def fake_find_similar_videos(*args, **kwargs):
    return []


storage_vector_module.find_similar_videos = fake_find_similar_videos
storage_sync_bridge_module.run_db_coroutine = lambda coro: None

sys.modules.setdefault("sqlalchemy", sqlalchemy_module)
sys.modules.setdefault("sqlalchemy.ext", sqlalchemy_ext_module)
sys.modules.setdefault("sqlalchemy.ext.asyncio", sqlalchemy_asyncio_module)
sys.modules.setdefault("storage", storage_module)
sys.modules.setdefault("storage.db", storage_db_module)
sys.modules.setdefault("storage.db.models", storage_models_module)
sys.modules.setdefault("storage.db.sync_bridge", storage_sync_bridge_module)
sys.modules.setdefault("storage.vector", storage_vector_module)

spec = importlib.util.spec_from_file_location(
    "reposts_under_test",
    PROJECT_ROOT / "storage" / "services" / "reposts.py",
)
assert spec is not None and spec.loader is not None
reposts = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reposts
spec.loader.exec_module(reposts)


# ---------------------------------------------------------------------------
# Test 1: parse_platform_upload_date — YYYYMMDD input
# ---------------------------------------------------------------------------
def test_parse_platform_upload_date_accepts_yyyymmdd():
    assert reposts.parse_platform_upload_date("20230615") == datetime(2023, 6, 15).date()


# ---------------------------------------------------------------------------
# Test 2: _is_different_post — same URL is not a different post
# ---------------------------------------------------------------------------
def test_same_url_is_not_a_different_post():
    current = reposts.VideoPostContext(
        original_url="https://youtube.com/watch?v=abc",
        uploader_handle="channel-a",
        upload_date=datetime(2024, 1, 10).date(),
    )
    matched = reposts.VideoPostContext(
        original_url="https://youtube.com/watch?v=abc/",
        uploader_handle="channel-a",
        upload_date=datetime(2023, 1, 1).date(),
    )
    assert reposts._is_different_post(current, matched) is False


# ---------------------------------------------------------------------------
# Test 3: _should_flag_repost — later post from different author
# ---------------------------------------------------------------------------
def test_later_post_from_different_author_is_flagged():
    current = reposts.VideoPostContext(
        original_url="https://youtube.com/watch?v=new",
        uploader_handle="channel-b",
        upload_date=datetime(2024, 6, 1).date(),
    )
    matched = reposts.VideoPostContext(
        original_url="https://youtube.com/watch?v=old",
        uploader_handle="channel-a",
        upload_date=datetime(2023, 1, 1).date(),
    )
    should_flag, _ = reposts._should_flag_repost(current, matched)
    assert should_flag is True


def test_earlier_post_is_not_flagged():
    current = reposts.VideoPostContext(
        original_url="https://youtube.com/watch?v=new",
        uploader_handle="channel-b",
        upload_date=datetime(2022, 1, 1).date(),
    )
    matched = reposts.VideoPostContext(
        original_url="https://youtube.com/watch?v=old",
        uploader_handle="channel-a",
        upload_date=datetime(2023, 1, 1).date(),
    )
    should_flag, rationale = reposts._should_flag_repost(current, matched)
    assert should_flag is False
    assert "not later" in rationale


def test_same_author_and_same_upload_date_is_not_flagged():
    current = reposts.VideoPostContext(
        original_url="https://youtube.com/watch?v=new",
        uploader_handle="channel-a",
        upload_date=datetime(2024, 1, 1).date(),
    )
    matched = reposts.VideoPostContext(
        original_url="https://youtube.com/watch?v=old",
        uploader_handle="@channel-a",
        upload_date=datetime(2024, 1, 1).date(),
    )
    should_flag, _ = reposts._should_flag_repost(current, matched)
    assert should_flag is False


# ---------------------------------------------------------------------------
# Test 4: _probability_from_distance — expected thresholds
# ---------------------------------------------------------------------------
def test_probability_from_distance_uses_expected_thresholds():
    assert reposts._probability_from_distance(0.01) == Decimal("0.9800")
    assert reposts._probability_from_distance(0.05) == Decimal("0.9200")
    assert reposts._probability_from_distance(0.12) == Decimal("0.8200")
    assert reposts._probability_from_distance(0.19) == Decimal("0.5500")


# ---------------------------------------------------------------------------
# Test 5: _serialize_match — API-safe types
# ---------------------------------------------------------------------------
def test_serialize_match_converts_database_values_to_api_safe_types():
    created_at = datetime(2026, 6, 8, 12, 30, tzinfo=timezone.utc)
    serialized = reposts._serialize_match(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "original_url": "https://example.com/source.mp4",
            "platform": "direct",
            "title": "Original clip",
            "thumbnail_path": "videos/source/thumb.jpg",
            "uploader_handle": "source-channel",
            "platform_upload_date": datetime(2024, 1, 2).date(),
            "created_at": created_at,
            "overall_risk_score": Decimal("0.42"),
            "similarity": Decimal("0.91"),
            "distance": Decimal("0.09"),
        }
    )

    assert serialized["uploaderHandle"] == "source-channel"
    assert serialized["platformUploadDate"] == "2024-01-02"
    assert serialized["createdAt"] == "2026-06-08T12:30:00+00:00"
    assert serialized["overallRiskScore"] == 0.42
    assert serialized["similarity"] == 0.91
    assert serialized["distance"] == 0.09


# ---------------------------------------------------------------------------
# Test 6: apply_repost_assessment_to_payload — merge behavior
# ---------------------------------------------------------------------------
def test_apply_repost_assessment_preserves_higher_existing_probability():
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

    assert merged["repost_probability"] == Decimal("0.7000")
    assert merged["misleading_context_score"] == Decimal("0.1000")
    assert merged["overall_risk_score"] == Decimal("0.2000")
    assert merged["reasons"]["flags"] == ["manual_review"]
    assert merged["reasons"]["repost"]["repostProbability"] == 0.55


def test_apply_repost_assessment_adds_flag_once_for_repost():
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

    assert merged["repost_probability"] == Decimal("0.9800")
    assert merged["misleading_context_score"] == Decimal("0.6500")
    assert merged["overall_risk_score"] == Decimal("0.6500")
    assert merged["reasons"]["flags"] == ["possible_repost"]
    assert "Reused footage" in merged["reasons"]["misleadingContext"]
