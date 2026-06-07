import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def get_venv_python() -> Path | None:
    if os.name == "nt":
        candidate = BACKEND_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = BACKEND_ROOT / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


@lru_cache
def get_ffmpeg_command() -> list[str]:
    env_path = os.environ.get("FFMPEG_PATH", "").strip()
    if env_path:
        return [env_path]

    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).exists():
            return [bundled]
    except Exception:
        pass

    which_path = shutil.which("ffmpeg")
    if which_path:
        return [which_path]

    raise FileNotFoundError(
        "ffmpeg not found. From backend/: pip install imageio-ffmpeg "
        "or winget install Gyan.FFmpeg"
    )


def get_ffmpeg_location_for_ytdlp() -> str:
    """yt-dlp accepts the full path to the ffmpeg binary (required for imageio's renamed exe)."""
    return get_ffmpeg_command()[0]


@lru_cache
def get_ffprobe_command() -> list[str]:
    env_path = os.environ.get("FFPROBE_PATH", "").strip()
    if env_path:
        return [env_path]

    which_path = shutil.which("ffprobe")
    if which_path:
        return [which_path]

    ffmpeg_path = Path(get_ffmpeg_command()[0])
    sibling = ffmpeg_path.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if sibling.exists():
        return [str(sibling)]

    raise FileNotFoundError(
        "ffprobe not found. Install ffmpeg (includes ffprobe) or set FFPROBE_PATH."
    )


def resolve_exiftool_path() -> str | None:
    env_path = os.environ.get("EXIFTOOL_PATH", "").strip()
    if env_path and Path(env_path).exists():
        return env_path

    which_path = shutil.which("exiftool")
    if which_path and Path(which_path).exists():
        return which_path

    for candidate in (
        Path(r"C:\Program Files\ExifTool\exiftool.exe"),
        Path(r"C:\Program Files (x86)\ExifTool\exiftool.exe"),
    ):
        if candidate.exists():
            return str(candidate)

    return None


@lru_cache
def get_ytdlp_command() -> list[str]:
    env_path = os.environ.get("YTDLP_PATH", "").strip()
    if env_path:
        return [env_path]

    venv_python = get_venv_python()
    if venv_python:
        return [str(venv_python), "-m", "yt_dlp"]

    which_path = shutil.which("yt-dlp")
    if which_path:
        return [which_path]

    try:
        import yt_dlp  # noqa: F401

        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass

    raise FileNotFoundError(
        "yt-dlp not found. From backend/: pip install yt-dlp "
        "or winget install yt-dlp.yt-dlp"
    )


def resolve_tesseract_path() -> str | None:
    env_path = os.environ.get("TESSERACT_CMD", "").strip()
    if env_path and Path(env_path).exists():
        return env_path

    which_path = shutil.which("tesseract")
    if which_path and Path(which_path).exists():
        return which_path

    for candidate in (
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Tesseract-OCR"
        / "tesseract.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Tesseract-OCR"
        / "tesseract.exe",
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
