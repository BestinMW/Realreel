from pathlib import Path

from .tools import get_ffmpeg_location_for_ytdlp


def download_youtube_video(youtube_url: str, job_dir: Path) -> Path:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. From backend/: pip install yt-dlp"
        ) from exc

    job_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(job_dir / "source.%(ext)s")
    ffmpeg_location = get_ffmpeg_location_for_ytdlp()

    ydl_opts = {
        "outtmpl": output_template,
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "ffmpeg_location": ffmpeg_location,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url.strip()])
    except Exception as exc:
        raise RuntimeError(f"yt-dlp download failed: {exc}") from exc

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
