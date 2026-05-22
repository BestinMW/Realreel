import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache
def get_ffmpeg_command() -> list[str]:
    env_path = os.environ.get("FFMPEG_PATH", "").strip()
    if env_path:
        return [env_path]

    which_path = shutil.which("ffmpeg")
    if which_path:
        return [which_path]

    try:
        import imageio_ffmpeg

        return [imageio_ffmpeg.get_ffmpeg_exe()]
    except Exception:
        pass

    raise FileNotFoundError(
        "ffmpeg not found. Run: pip install imageio-ffmpeg (in backend venv), "
        "or install system ffmpeg: winget install Gyan.FFmpeg"
    )


@lru_cache
def get_ytdlp_command() -> list[str]:
    env_path = os.environ.get("YTDLP_PATH", "").strip()
    if env_path:
        return [env_path]

    which_path = shutil.which("yt-dlp")
    if which_path:
        return [which_path]

    try:
        import yt_dlp  # noqa: F401

        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass

    raise FileNotFoundError(
        "yt-dlp not found. Run: pip install yt-dlp (in backend venv), "
        "or install system yt-dlp: winget install yt-dlp.yt-dlp"
    )


def resolve_tesseract_path() -> str | None:
    env_path = os.environ.get("TESSERACT_CMD", "").strip()
    if env_path and Path(env_path).exists():
        return env_path

    which_path = shutil.which("tesseract")
    if which_path:
        return which_path

    for candidate in (
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ):
        if candidate.exists():
            return str(candidate)

    return None


def configure_tesseract() -> str | None:
    try:
        import pytesseract
    except ImportError:
        return None

    path = resolve_tesseract_path()
    if path:
        pytesseract.pytesseract.tesseract_cmd = path
    return path
