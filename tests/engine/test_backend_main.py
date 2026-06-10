import json

import pytest

import backend.main as main
from pipeline import tools


class NeverDisconnectedRequest:
    async def is_disconnected(self):
        return False


def test_health_reports_resolved_tool_paths(monkeypatch):
    monkeypatch.setattr(tools, "get_ffmpeg_command", lambda: ["ffmpeg-test"])
    monkeypatch.setattr(tools, "get_ytdlp_command", lambda: ["python", "-m", "yt_dlp"])
    monkeypatch.setattr(tools, "resolve_tesseract_path", lambda: "tesseract-test")

    result = main.health()

    assert result["ok"] is True
    assert result["version"] == "2026-05-22"
    assert result["tools"]["ffmpeg"] == "ffmpeg-test"
    assert result["tools"]["yt_dlp"] == "python -m yt_dlp"
    assert result["tools"]["tesseract"] == "tesseract-test"


def test_health_reports_missing_tool(monkeypatch):
    def missing_ffmpeg():
        raise FileNotFoundError("missing ffmpeg")

    monkeypatch.setattr(tools, "get_ffmpeg_command", missing_ffmpeg)
    monkeypatch.setattr(tools, "get_ytdlp_command", lambda: ["yt-dlp"])
    monkeypatch.setattr(tools, "resolve_tesseract_path", lambda: None)

    result = main.health()

    assert result["tools"]["ffmpeg"] == "missing: missing ffmpeg"
    assert result["tools"]["yt_dlp"] == "yt-dlp"
    assert result["tools"]["tesseract"] is None


@pytest.mark.anyio
async def test_process_youtube_streams_pipeline_events(monkeypatch):
    captured = {}

    def fake_process(url, *, fast_processing_mode):
        captured["url"] = url
        captured["fast_processing_mode"] = fast_processing_mode
        return [
            {"type": "progress", "progress": 10, "stage": "Starting"},
            {"type": "complete", "progress": 100, "stage": "Done", "result": {"success": True}},
        ]

    monkeypatch.setattr(main, "process_youtube_video", fake_process)

    response = await main.process_youtube(
        main.ProcessRequest(videoUrl="https://example.com/video", fastProcessingMode=True),
        NeverDisconnectedRequest(),
    )
    chunks = [chunk async for chunk in response.body_iterator]
    events = [json.loads(chunk.decode("utf-8")) for chunk in chunks]

    assert captured == {
        "url": "https://example.com/video",
        "fast_processing_mode": True,
    }
    assert response.media_type == "application/x-ndjson; charset=utf-8"
    assert events[-1]["type"] == "complete"


@pytest.mark.anyio
async def test_process_youtube_accepts_legacy_youtube_url(monkeypatch):
    captured = {}

    def fake_process(url, *, fast_processing_mode):
        captured["url"] = url
        captured["fast_processing_mode"] = fast_processing_mode
        return [{"type": "error", "message": "bad url"}]

    monkeypatch.setattr(main, "process_youtube_video", fake_process)

    response = await main.process_youtube(
        main.ProcessRequest(youtubeUrl="https://youtu.be/example"),
        NeverDisconnectedRequest(),
    )
    chunks = [chunk async for chunk in response.body_iterator]

    assert captured == {
        "url": "https://youtu.be/example",
        "fast_processing_mode": None,
    }
    assert json.loads(chunks[0].decode("utf-8")) == {
        "type": "error",
        "message": "bad url",
    }
