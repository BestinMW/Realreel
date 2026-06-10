import asyncio
import builtins
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import download, tools, youtube
from storage.db import sync_bridge


def test_youtube_parser_extra_branches():
    assert youtube.parse_video_url("http://[broken") is None
    assert youtube.parse_youtube_url(123) is None
    assert youtube.parse_youtube_url("http://[broken") is None
    assert youtube.parse_video_url("https://vm.tiktok.com/ZMabc/")["id"] == "ZMabc"
    assert youtube.parse_video_url("https://www.tiktok.com/t/ZT123/")["id"] == "ZT123"
    assert youtube.parse_video_url("https://www.tiktok.com/@user/clip/name")["id"] == "_user-clip-name"
    assert youtube.parse_video_url("https://www.instagram.com/stories/user/story123/")["id"] == "story123"
    assert youtube.parse_video_url("https://example.com/file.txt") is None
    assert youtube.parse_video_url("https://example.com/video.MOV")["platform"] == "direct"


def test_download_import_and_error_branches(monkeypatch, tmp_path):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yt_dlp":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "yt_dlp", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="yt-dlp is not installed"):
        download.extract_video_info("https://example.com")
    with pytest.raises(RuntimeError, match="yt-dlp is not installed"):
        download.download_video_with_info("https://example.com", tmp_path)

    with pytest.raises(RuntimeError, match="no downloaded video"):
        download.find_downloaded_video(tmp_path)


def test_download_extract_video_info_runtime_errors(monkeypatch):
    class EmptyYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=False):
            return None

        def sanitize_info(self, info, download=False):
            return info

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=EmptyYoutubeDL))
    monkeypatch.setattr(download, "get_ffmpeg_location_for_ytdlp", lambda: "ffmpeg")
    with pytest.raises(RuntimeError, match="no metadata"):
        download.extract_video_info("https://example.com")

    class BadSanitizeYoutubeDL(EmptyYoutubeDL):
        def extract_info(self, url, download=False):
            return {"id": "ok"}

        def sanitize_info(self, info, download=False):
            return "not a dict"

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=BadSanitizeYoutubeDL))
    with pytest.raises(RuntimeError, match="metadata object"):
        download.extract_video_info("https://example.com")


def test_download_alias_functions_delegate(monkeypatch, tmp_path):
    monkeypatch.setattr(
        download,
        "download_video_with_info",
        lambda url, job_dir: (job_dir / "source.mp4", {"id": "abc"}),
    )

    assert download.download_video("https://example.com/video", tmp_path) == tmp_path / "source.mp4"
    assert download.download_youtube_video("https://youtu.be/abc", tmp_path) == tmp_path / "source.mp4"


def test_tools_venv_path_and_which_branches(monkeypatch, tmp_path):
    fake_python = tmp_path / "python.exe"
    fake_python.write_text("exe", encoding="utf-8")
    monkeypatch.setattr(tools, "BACKEND_ROOT", tmp_path)
    monkeypatch.setattr(tools.os, "name", "nt")
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts" / "python.exe").write_text("exe", encoding="utf-8")
    assert tools.get_venv_python() == tmp_path / ".venv" / "Scripts" / "python.exe"

    tools.get_ffmpeg_command.cache_clear()
    tools.get_ffprobe_command.cache_clear()
    tools.get_ytdlp_command.cache_clear()
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.delenv("FFPROBE_PATH", raising=False)
    monkeypatch.delenv("YTDLP_PATH", raising=False)
    real_import = builtins.__import__

    def hide_imageio(name, *args, **kwargs):
        if name == "imageio_ffmpeg":
            raise ImportError("hidden for PATH branch")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", hide_imageio)

    def fake_which(name):
        if name == "ffmpeg":
            return str(tmp_path / "ffmpeg.exe")
        if name == "ffprobe":
            return str(tmp_path / "ffprobe.exe")
        if name == "yt-dlp":
            return str(tmp_path / "yt-dlp.exe")
        if name == "tesseract":
            return str(tmp_path / "tesseract.exe")
        if name == "exiftool":
            return str(tmp_path / "exiftool.exe")
        return None

    for name in ("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe", "tesseract.exe", "exiftool.exe"):
        (tmp_path / name).write_text("exe", encoding="utf-8")
    monkeypatch.setattr(tools.shutil, "which", fake_which)

    assert tools.get_ffmpeg_command() == [str(tmp_path / "ffmpeg.exe")]
    assert tools.get_ffprobe_command() == [str(tmp_path / "ffprobe.exe")]
    assert tools.get_ytdlp_command() == [str(tmp_path / ".venv" / "Scripts" / "python.exe"), "-m", "yt_dlp"]
    assert tools.resolve_tesseract_path() == str(tmp_path / "tesseract.exe")

    tools.get_ytdlp_command.cache_clear()
    monkeypatch.setattr(tools, "get_venv_python", lambda: None)
    assert tools.get_ytdlp_command() == [str(tmp_path / "yt-dlp.exe")]

    monkeypatch.delenv("EXIFTOOL_PATH", raising=False)
    assert tools.resolve_exiftool_path() == str(tmp_path / "exiftool.exe")


@pytest.mark.anyio
async def test_sync_bridge_initialization_and_session(monkeypatch):
    sync_bridge._engine = None
    sync_bridge._session_factory = None
    created = {}

    class FakeSessionContext:
        async def __aenter__(self):
            return "session"

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeFactory:
        def __call__(self):
            return FakeSessionContext()

    def fake_create_async_engine(url, **kwargs):
        created["url"] = url
        created["kwargs"] = kwargs
        return "engine"

    monkeypatch.setattr(sync_bridge, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(sync_bridge, "async_sessionmaker", lambda **kwargs: FakeFactory())

    await sync_bridge._init_bridge()
    assert created["kwargs"]["pool_pre_ping"] is True
    assert sync_bridge._engine == "engine"

    sessions = []
    async for session in sync_bridge.bridge_session():
        sessions.append(session)
    assert sessions == ["session"]


def test_sync_bridge_run_db_coroutine_uses_threadsafe_runner(monkeypatch):
    sync_bridge._engine = "engine"
    sync_bridge._session_factory = "factory"
    calls = []

    class FakeFuture:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

    def fake_run_coroutine_threadsafe(coro, loop):
        calls.append((coro, loop))
        if len(calls) == 1:
            coro.close()
            return FakeFuture(None)
        coro.close()
        return FakeFuture("done")

    async def work():
        return "done"

    monkeypatch.setattr(sync_bridge, "_ensure_loop", lambda: "loop")
    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", fake_run_coroutine_threadsafe)

    assert sync_bridge.run_db_coroutine(work()) == "done"
    assert len(calls) == 2


def test_sync_bridge_ensure_loop_starts_thread(monkeypatch):
    sync_bridge._loop = None
    sync_bridge._loop_thread = None

    class FakeThread:
        def __init__(self, target, name, daemon):
            self.target = target
            self.name = name
            self.daemon = daemon
            self.started = False

        def start(self):
            self.started = True
            sync_bridge._loop = "created-loop"

    class FakeReady:
        def wait(self):
            return None

    monkeypatch.setattr(sync_bridge.threading, "Thread", FakeThread)
    monkeypatch.setattr(sync_bridge, "_loop_ready", FakeReady())

    assert sync_bridge._ensure_loop() == "created-loop"
    assert sync_bridge._loop_thread.name == "db-sync-bridge"
