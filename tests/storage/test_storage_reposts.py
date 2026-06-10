"""Unit tests for repost detection rules in the storage layer.

SQLAlchemy and database calls are stubbed — these tests run without Postgres.

Run:
    pytest tests/storage/test_storage_reposts.py -v
"""

import asyncio
import importlib.util
import sys
import types
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class _FakeSelectQuery:
    def where(self, *args, **kwargs):
        return self

    def limit(self, count):
        return self


sqlalchemy_module = types.ModuleType("sqlalchemy")
sqlalchemy_module.select = lambda *args, **kwargs: _FakeSelectQuery()
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
    original_url = object()


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
reposts.Video = storage_models_module.Video


# ---------------------------------------------------------------------------
# Date parsing and upload-date resolution
# ---------------------------------------------------------------------------
def test_parse_platform_upload_date_handles_common_formats_and_edge_cases():
    assert reposts.parse_platform_upload_date("20230615") == date(2023, 6, 15)
    assert reposts.parse_platform_upload_date(None) is None
    assert reposts.parse_platform_upload_date("") is None

    when = datetime(2024, 3, 15, 18, 30, tzinfo=timezone.utc)
    assert reposts.parse_platform_upload_date(when) == date(2024, 3, 15)
    assert reposts.parse_platform_upload_date(when.date()) == date(2024, 3, 15)
    assert reposts.parse_platform_upload_date("2024-06-01T12:00:00Z") == date(2024, 6, 1)
    assert reposts.parse_platform_upload_date("20239999") is None
    assert reposts.parse_platform_upload_date("not-a-date") is None


def test_upload_date_resolution_and_post_context():
    video = storage_models_module.Video()
    video.platform_upload_date = date(2024, 5, 1)
    video.reasons = {"platform": {"uploadDate": "20230101"}}
    assert reposts._resolve_upload_date(video) == date(2024, 5, 1)

    legacy_only = storage_models_module.Video()
    legacy_only.platform_upload_date = None
    legacy_only.reasons = {"platform": {"uploadDate": "20230115"}}
    assert reposts._resolve_upload_date(legacy_only) == date(2023, 1, 15)
    assert reposts._legacy_upload_date_from_reasons(None) is None
    assert reposts._legacy_upload_date_from_reasons({"platform": "youtube"}) is None

    video.original_url = "https://example.com/video"
    video.uploader_handle = "@creator"
    video.platform_upload_date = date(2024, 2, 2)
    video.reasons = None
    model_context = reposts._post_context(video)
    assert model_context.original_url == "https://example.com/video"
    assert model_context.uploader_handle == "@creator"
    assert model_context.upload_date == date(2024, 2, 2)

    dict_context = reposts._post_context(
        {
            "original_url": "https://example.com/dict",
            "uploader_handle": "creator",
            "platform_upload_date": "20240301",
        }
    )
    assert dict_context.upload_date == date(2024, 3, 1)


# ---------------------------------------------------------------------------
# Repost matching rules
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


def test_should_flag_repost_covers_author_date_and_timing_rules():
    later_different_author = (
        reposts.VideoPostContext(
            "https://youtube.com/watch?v=new", "channel-b", date(2024, 6, 1)
        ),
        reposts.VideoPostContext(
            "https://youtube.com/watch?v=old", "channel-a", date(2023, 1, 1)
        ),
    )
    flagged, rationale = reposts._should_flag_repost(*later_different_author)
    assert flagged is True
    assert "different author" in rationale

    later_same_author = (
        reposts.VideoPostContext(
            "https://youtube.com/watch?v=new", "channel-a", date(2024, 6, 1)
        ),
        reposts.VideoPostContext(
            "https://youtube.com/watch?v=old", "channel-a", date(2023, 1, 1)
        ),
    )
    flagged, rationale = reposts._should_flag_repost(*later_same_author)
    assert flagged is True
    assert "different publish date" in rationale

    earlier = (
        reposts.VideoPostContext(
            "https://youtube.com/watch?v=new", "channel-b", date(2022, 1, 1)
        ),
        reposts.VideoPostContext(
            "https://youtube.com/watch?v=old", "channel-a", date(2023, 1, 1)
        ),
    )
    flagged, rationale = reposts._should_flag_repost(*earlier)
    assert flagged is False
    assert "not later" in rationale

    same_author_same_date = (
        reposts.VideoPostContext(
            "https://youtube.com/watch?v=new", "channel-a", date(2024, 1, 1)
        ),
        reposts.VideoPostContext(
            "https://youtube.com/watch?v=old", "@channel-a", date(2024, 1, 1)
        ),
    )
    flagged, _ = reposts._should_flag_repost(*same_author_same_date)
    assert flagged is False


def test_probability_from_distance_uses_expected_thresholds():
    assert reposts._probability_from_distance(0.01) == Decimal("0.9800")
    assert reposts._probability_from_distance(0.05) == Decimal("0.9200")
    assert reposts._probability_from_distance(0.12) == Decimal("0.8200")
    assert reposts._probability_from_distance(0.19) == Decimal("0.5500")


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
# assess_repost_risk — async assessment paths
# ---------------------------------------------------------------------------
class _FakeExecuteResult:
    def __init__(self, video):
        self._video = video

    def scalar_one_or_none(self):
        return self._video


class _FakeAsyncSession:
    def __init__(self, video=None):
        self._video = video

    async def execute(self, query):
        return _FakeExecuteResult(self._video)


def _fake_video_record(**overrides):
    video = storage_models_module.Video()
    video.id = overrides.get("id", uuid.uuid4())
    video.original_url = overrides.get("original_url", "https://youtube.com/watch?v=stored")
    video.platform = types.SimpleNamespace(value=overrides.get("platform", "youtube"))
    video.title = overrides.get("title", "Stored clip")
    video.thumbnail_path = overrides.get("thumbnail_path", "videos/stored/thumb.jpg")
    video.uploader_handle = overrides.get("uploader_handle", "channel-a")
    video.platform_upload_date = overrides.get(
        "platform_upload_date", datetime(2023, 1, 1).date()
    )
    video.reasons = overrides.get("reasons")
    video.created_at = overrides.get(
        "created_at", datetime(2024, 1, 1, tzinfo=timezone.utc)
    )
    video.overall_risk_score = overrides.get("overall_risk_score", Decimal("0.42"))
    video.file_sha256 = overrides.get("file_sha256", "abc123")
    return video


def _patch_reposts_select():
    original_select = reposts.select
    reposts.select = lambda *args, **kwargs: _FakeSelectQuery()
    return original_select


def _run_assess_repost_risk(session, **kwargs):
    original_select = _patch_reposts_select()
    try:
        return asyncio.run(reposts.assess_repost_risk(session, **kwargs))
    finally:
        reposts.select = original_select


def test_assess_repost_risk_skips_when_no_embedding_is_available():
    result = _run_assess_repost_risk(
        _FakeAsyncSession(),
        embedding=None,
        file_sha256=None,
    )

    assert result["isRepost"] is False
    assert result["repostProbability"] is None
    assert result["matches"] == []
    assert "No video embedding" in result["rationale"]


def test_assess_repost_risk_reports_no_similar_videos():
    session = _FakeAsyncSession()
    original_finder = reposts.find_similar_videos
    reposts.find_similar_videos = fake_find_similar_videos

    try:
        result = _run_assess_repost_risk(
            session,
            embedding=[0.1, 0.2, 0.3],
            file_sha256=None,
        )
    finally:
        reposts.find_similar_videos = original_finder

    assert result["isRepost"] is False
    assert result["repostProbability"] == Decimal("0.0000")
    assert result["matches"] == []
    assert "No similar previously analyzed videos" in result["rationale"]


def test_assess_repost_risk_handles_exact_hash_matches():
    stored = _fake_video_record(
        original_url="https://youtube.com/watch?v=original",
        uploader_handle="channel-a",
        platform_upload_date=datetime(2023, 1, 1).date(),
    )
    duplicate = _run_assess_repost_risk(
        _FakeAsyncSession(video=stored),
        embedding=[0.1, 0.2],
        file_sha256="abc123",
        original_url="https://youtube.com/watch?v=reupload",
        uploader_handle="channel-b",
        upload_date="20240601",
    )
    assert duplicate["isRepost"] is True
    assert duplicate["repostProbability"] == Decimal("1.0000")
    assert "SHA-256 hash" in duplicate["rationale"]
    assert "different author" in duplicate["rationale"]

    same_source = _run_assess_repost_risk(
        _FakeAsyncSession(
            video=_fake_video_record(
                original_url="https://youtube.com/watch?v=same",
                uploader_handle="channel-a",
                platform_upload_date=datetime(2024, 6, 1).date(),
            )
        ),
        embedding=[0.1, 0.2],
        file_sha256="abc123",
        original_url="https://youtube.com/watch?v=same",
        uploader_handle="channel-a",
        upload_date="20240601",
    )
    assert same_source["isRepost"] is False
    assert same_source["repostProbability"] == Decimal("0.0000")
    assert "same source" in same_source["rationale"]


async def _fake_find_confirmed_similar_repost(*args, **kwargs):
    return [
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
            "original_url": "https://youtube.com/watch?v=old",
            "platform": "youtube",
            "title": "Older clip",
            "thumbnail_path": "videos/old/thumb.jpg",
            "uploader_handle": "channel-a",
            "platform_upload_date": datetime(2023, 1, 1).date(),
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "overall_risk_score": Decimal("0.50"),
            "similarity": 0.95,
            "distance": 0.05,
        }
    ]


async def _fake_find_possible_but_unconfirmed_repost(*args, **kwargs):
    return [
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000003"),
            "original_url": "https://youtube.com/watch?v=old",
            "platform": "youtube",
            "title": "Older clip",
            "thumbnail_path": None,
            "uploader_handle": "channel-a",
            "platform_upload_date": datetime(2023, 1, 1).date(),
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "overall_risk_score": Decimal("0.40"),
            "similarity": 0.88,
            "distance": 0.15,
        }
    ]


async def _fake_find_similar_but_not_repost_by_rules(*args, **kwargs):
    return [
        {
            "id": uuid.UUID("00000000-0000-0000-0000-000000000004"),
            "original_url": "https://youtube.com/watch?v=old",
            "platform": "youtube",
            "title": "Older clip",
            "thumbnail_path": None,
            "uploader_handle": "channel-a",
            "platform_upload_date": datetime(2024, 6, 1).date(),
            "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            "overall_risk_score": Decimal("0.30"),
            "similarity": 0.90,
            "distance": 0.10,
        }
    ]


def test_assess_repost_risk_handles_similar_video_outcomes():
    session = _FakeAsyncSession()
    original_finder = reposts.find_similar_videos

    reposts.find_similar_videos = _fake_find_confirmed_similar_repost
    try:
        confirmed = _run_assess_repost_risk(
            session,
            embedding=[0.1, 0.2, 0.3],
            original_url="https://youtube.com/watch?v=new",
            uploader_handle="channel-b",
            upload_date="20240601",
        )
    finally:
        reposts.find_similar_videos = original_finder

    assert confirmed["isRepost"] is True
    assert confirmed["repostProbability"] == Decimal("0.9200")
    assert "Closest saved video is 95% similar" in confirmed["rationale"]

    reposts.find_similar_videos = _fake_find_possible_but_unconfirmed_repost
    try:
        below_threshold = _run_assess_repost_risk(
            session,
            embedding=[0.1, 0.2, 0.3],
            original_url="https://youtube.com/watch?v=new",
            uploader_handle="channel-b",
            upload_date="20240601",
        )
    finally:
        reposts.find_similar_videos = original_finder

    assert below_threshold["isRepost"] is False
    assert below_threshold["repostProbability"] == Decimal("0.5500")
    assert "Closest saved video is 88% similar" in below_threshold["rationale"]

    reposts.find_similar_videos = _fake_find_similar_but_not_repost_by_rules
    try:
        not_by_rules = _run_assess_repost_risk(
            session,
            embedding=[0.1, 0.2, 0.3],
            original_url="https://youtube.com/watch?v=new",
            uploader_handle="channel-b",
            upload_date="20240101",
        )
    finally:
        reposts.find_similar_videos = original_finder

    assert not_by_rules["isRepost"] is False
    assert not_by_rules["repostProbability"] == Decimal("0.0000")
    assert len(not_by_rules["matches"]) == 1
    assert "does not count as a repost" in not_by_rules["rationale"]


# ---------------------------------------------------------------------------
# run_repost_assessment_sync — bridge and failure handling
# ---------------------------------------------------------------------------
async def _empty_bridge_session():
    return
    yield _FakeAsyncSession()


def _install_bridge_session(factory):
    bridge_module = sys.modules["storage.db.sync_bridge"]
    original = getattr(bridge_module, "bridge_session", None)
    bridge_module.bridge_session = factory
    return bridge_module, original


def _restore_bridge_session(bridge_module, original):
    if original is None:
        if hasattr(bridge_module, "bridge_session"):
            delattr(bridge_module, "bridge_session")
    else:
        bridge_module.bridge_session = original


def _raise_database_unavailable(coro):
    coro.close()
    raise RuntimeError("Database unavailable")


def test_run_repost_assessment_sync_handles_bridge_failures():
    original_run = reposts.run_db_coroutine
    bridge_module, original_bridge = _install_bridge_session(_empty_bridge_session)
    reposts.run_db_coroutine = lambda coro: asyncio.run(coro)

    try:
        empty_bridge = reposts.run_repost_assessment_sync(
            file_sha256=None,
            embedding=None,
        )
    finally:
        reposts.run_db_coroutine = original_run
        _restore_bridge_session(bridge_module, original_bridge)

    assert empty_bridge["skipped"] is True
    assert empty_bridge["skipReason"] == "Database session was not available."

    reposts.run_db_coroutine = _raise_database_unavailable
    try:
        db_failure = reposts.run_repost_assessment_sync(file_sha256="deadbeef")
    finally:
        reposts.run_db_coroutine = original_run

    assert db_failure["skipped"] is True
    assert db_failure["skipReason"] == "Database unavailable"
