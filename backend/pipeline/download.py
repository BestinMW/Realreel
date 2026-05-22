import subprocess
from pathlib import Path

from .tools import get_ytdlp_command


def download_youtube_video(youtube_url: str, job_dir: Path) -> Path:
    job_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(job_dir / "source.%(ext)s")
    command = [
        *get_ytdlp_command(),
        youtube_url.strip(),
        "--no-playlist",
        "-f",
        "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc
    if result.returncode != 0:
        details = result.stderr or result.stdout or "yt-dlp failed"
        raise RuntimeError(details.strip())
    return find_downloaded_video(job_dir)


def find_downloaded_video(job_dir: Path) -> Path:
    videos = [
        path
        for path in job_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not videos:
        raise RuntimeError("yt-dlp finished, but no downloaded video file was found.")

    def sort_key(path: Path) -> tuple[int, str]:
        looks_merged = ".f" not in path.name
        return (0 if looks_merged else 1, path.name)

    videos.sort(key=sort_key)
    return videos[0]
