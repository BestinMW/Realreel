from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .download import extract_video_info
from .tools import get_ffprobe_command, resolve_exiftool_path


def get_video_metadata(video_path: Path | str) -> dict[str, Any]:
    """Raw ffprobe JSON for format and streams."""
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    result = subprocess.run(
        [
            *get_ffprobe_command(),
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "ffprobe failed").strip()
        raise RuntimeError(stderr)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe returned invalid JSON") from exc


def get_platform_metadata(url: str) -> dict[str, Any]:
    """Raw yt-dlp info dict (equivalent to --dump-json), without downloading."""
    return extract_video_info(url)


def get_embedded_metadata(video_path: Path | str) -> list[dict[str, Any]]:
    """Raw exiftool JSON output for the file."""
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {path}")

    exiftool_path = resolve_exiftool_path()
    if not exiftool_path:
        raise FileNotFoundError(
            "exiftool not found. Install from https://exiftool.org/ or set EXIFTOOL_PATH."
        )

    result = subprocess.run(
        [exiftool_path, "-json", "-n", "-G", "-struct", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "exiftool failed").strip()
        raise RuntimeError(stderr)

    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("exiftool returned invalid JSON") from exc

    if not isinstance(payload, list):
        raise RuntimeError("exiftool returned unexpected JSON shape")
    return payload
