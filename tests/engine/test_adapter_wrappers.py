from pathlib import Path

import pytest

from backend.adapters import object_storage, persistence, reposts


def test_storage_upload_error_detects_payload_too_large():
    direct = object_storage.SupabaseStorageUploadError(
        storage_path="videos/raw.mp4",
        status_code=413,
        message="too big",
    )
    textual = object_storage.SupabaseStorageUploadError(
        storage_path="videos/raw.mp4",
        status_code=400,
        message='{"statusCode":"413","message":"maximum allowed size"}',
    )

    assert direct.is_payload_too_large
    assert textual.is_payload_too_large
    assert "videos/raw.mp4" in str(direct)


def test_get_supabase_config_requires_env(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Supabase storage is not configured"):
        object_storage.get_supabase_config()


def test_ensure_storage_buckets_creates_only_missing_buckets(monkeypatch):
    calls = {"created": []}

    class Response:
        def __init__(self, status_code=200, payload=None, text="ok"):
            self.status_code = status_code
            self._payload = payload or []
            self.text = text

        def json(self):
            return self._payload

    def fake_get(url, **kwargs):
        assert url == "https://example.supabase.co/storage/v1/bucket"
        return Response(payload=[{"name": "existing"}])

    def fake_post(url, **kwargs):
        calls["created"].append(kwargs["json"]["name"])
        return Response()

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(object_storage.httpx, "get", fake_get, raising=False)
    monkeypatch.setattr(object_storage.httpx, "post", fake_post)
    object_storage._ensured_bucket_names.clear()

    object_storage.ensure_storage_buckets({"existing", "new-bucket"})

    assert calls["created"] == ["new-bucket"]
    assert object_storage._ensured_bucket_names == {"existing", "new-bucket"}


def test_upload_to_supabase_storage_encodes_path_and_returns_storage_path(
    monkeypatch, tmp_path
):
    uploaded = {}
    local_path = tmp_path / "thumb.jpg"
    local_path.write_bytes(b"image-bytes")

    class Response:
        status_code = 200
        text = "ok"

    def fake_post(url, **kwargs):
        uploaded["url"] = url
        uploaded["headers"] = kwargs["headers"]
        uploaded["content"] = kwargs["content"]
        return Response()

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setattr(object_storage.httpx, "post", fake_post)

    result = object_storage.upload_to_supabase_storage(
        bucket="analysis",
        storage_path="video one/results file.json",
        local_path=local_path,
        content_type="application/json",
    )

    assert result == "video one/results file.json"
    assert uploaded["url"].endswith("/analysis/video%20one/results%20file.json")
    assert uploaded["headers"]["x-upsert"] == "true"
    assert uploaded["content"] == b"image-bytes"


def test_persistence_skips_when_database_save_disabled(monkeypatch):
    monkeypatch.setattr(persistence, "DATABASE_SAVE_ENABLED", False)

    result = persistence.persist_analysis_record(
        original_url="https://example.com/video",
        platform="youtube",
        file_sha256="a" * 64,
        download_info={},
        transcript={},
        raw_video_storage_path=None,
        thumbnail_storage_path=None,
        transcript_storage_path="transcript.json",
        claim_analysis={},
        thumbnail_clickbait_analysis={},
        metadata_analysis={},
        repost_result={},
        repost_risk=None,
        analysis_paths={},
    )

    assert result["skipped"] is True
    assert result["ok"] is False


def test_persistence_builds_payload_when_enabled(monkeypatch):
    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return {"payload": True}

    def fake_persist(payload):
        return {"ok": True, "videoId": "video-1", "payload": payload}

    monkeypatch.setattr(persistence, "DATABASE_SAVE_ENABLED", True)
    monkeypatch.setattr(persistence, "build_db_video_payload", fake_build)
    monkeypatch.setattr(persistence, "persist_db_video_sync", fake_persist)

    result = persistence.persist_analysis_record(
        original_url="https://example.com/video",
        platform="youtube",
        file_sha256="a" * 64,
        download_info={"upload_date": "20250101"},
        transcript={"text": "hello"},
        raw_video_storage_path="raw.mp4",
        thumbnail_storage_path="thumb.jpg",
        transcript_storage_path="transcript.json",
        claim_analysis={"claim": "test"},
        thumbnail_clickbait_analysis={"clickbaitScore": 0.1},
        metadata_analysis={"ok": True},
        repost_result={"isRepost": False},
        repost_risk=0.2,
        analysis_paths={"claim": "claim.json"},
    )

    assert result["ok"] is True
    assert result["payload"] == {"payload": True}
    assert captured["transcript_text"] == "hello"
    assert captured["raw_video_path"] == "raw.mp4"


def test_repost_assessment_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(reposts, "REPOST_ASSESSMENT_ENABLED", False)

    assessment, match_date, safe_result, risk = reposts.assess_repost_history(
        "a" * 64,
        original_url="https://example.com/video",
        download_info={},
    )

    assert assessment["skipped"] is True
    assert match_date is None
    assert safe_result["isRepost"] is False
    assert risk is None


def test_repost_assessment_uses_storage_service_when_enabled(monkeypatch):
    raw_assessment = {"matches": [{"createdAt": "2025-01-01"}]}

    def fake_run(**kwargs):
        assert kwargs["uploader_handle"] == "channel-name"
        assert kwargs["upload_date"] == "20250101"
        return raw_assessment

    monkeypatch.setattr(reposts, "REPOST_ASSESSMENT_ENABLED", True)
    monkeypatch.setattr(reposts, "run_repost_assessment_sync", fake_run)
    monkeypatch.setattr(reposts, "json_safe_assessment", lambda value: {"safe": value})
    monkeypatch.setattr(reposts, "extract_repost_match_date", lambda value: "2025-01-01")
    monkeypatch.setattr(reposts, "repost_risk_score", lambda value: 0.75)

    assessment, match_date, safe_result, risk = reposts.assess_repost_history(
        "a" * 64,
        original_url="https://example.com/video",
        download_info={"channel": "channel-name", "upload_date": "20250101"},
    )

    assert assessment == raw_assessment
    assert match_date == "2025-01-01"
    assert safe_result == {"safe": raw_assessment}
    assert risk == 0.75
