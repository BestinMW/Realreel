from pathlib import Path
from typing import Any

from .tools import get_ffmpeg_location_for_ytdlp


def extract_video_info(url: str) -> dict[str, Any]:
    """Return yt-dlp's info dict for a URL (same fields as --dump-json), without downloading.

    Args:
        url (str): Video page URL to inspect.

    Returns:
        dict[str, Any]: Sanitized yt-dlp metadata object for the resolved video entry.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. From backend/: pip install yt-dlp"
        ) from exc

    cleaned_url = url.strip()
    if not cleaned_url:
        raise ValueError("URL is required.")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "ffmpeg_location": get_ffmpeg_location_for_ytdlp(),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(cleaned_url, download=False)
            if not info:
                raise RuntimeError("yt-dlp returned no metadata for this URL.")

            if info.get("_type") == "playlist" and info.get("entries"):
                first_entry = next((entry for entry in info["entries"] if entry), None)
                if not first_entry:
                    raise RuntimeError("yt-dlp playlist had no usable entries.")
                info = first_entry

            sanitized = ydl.sanitize_info(info, download=False)
            if not isinstance(sanitized, dict):
                raise RuntimeError("yt-dlp did not return a metadata object.")
            return sanitized
    except Exception as exc:
        if isinstance(exc, (ValueError, RuntimeError)):
            raise
        raise RuntimeError(f"yt-dlp metadata extraction failed: {exc}") from exc



def download_video(video_url: str, job_dir: Path) -> Path:
    """Download a video file into a job directory.

    Args:
        video_url (str): Source video URL accepted by yt-dlp.
        job_dir (Path): Directory where the downloaded file is written.

    Returns:
        Path: Filesystem path to the downloaded video file.
    """
    video_path, _ = download_video_with_info(video_url, job_dir)
    return video_path


def download_video_with_info(video_url: str, job_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Download a video file and return yt-dlp metadata for the download.

    Args:
        video_url (str): Source video URL accepted by yt-dlp.
        job_dir (Path): Directory where the downloaded file is written.

    Returns:
        tuple[Path, dict[str, Any]]: Pair of the downloaded video path and the
            sanitized yt-dlp info dict produced during extraction.
    """
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

    info: dict[str, Any] = {}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            extracted = ydl.extract_info(video_url.strip(), download=True)
            sanitized = ydl.sanitize_info(extracted) if extracted else {}
            if isinstance(sanitized, dict):
                info = sanitized
    except Exception as exc:
        raise RuntimeError(f"yt-dlp download failed: {exc}") from exc

    return find_downloaded_video(job_dir), info


def download_youtube_video(youtube_url: str, job_dir: Path) -> Path:
    """Download a YouTube video into a job directory.

    Args:
        youtube_url (str): YouTube watch, shorts, or youtu.be URL.
        job_dir (Path): Directory where the downloaded file is written.

    Returns:
        Path: Filesystem path to the downloaded video file.
    """
    return download_video(youtube_url, job_dir)


def find_downloaded_video(job_dir: Path) -> Path:
    """Locate the primary downloaded video file in a job directory.

    Args:
        job_dir (Path): Directory scanned for downloaded video files.

    Returns:
        Path: Preferred merged video file when multiple candidates exist.
    """
    videos = [
        path
        for path in job_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}
    ]
    if not videos:
        raise RuntimeError("yt-dlp finished, but no downloaded video file was found.")

    def sort_key(path: Path) -> tuple[int, str]:
        """Prefer merged yt-dlp outputs over separate format fragments.

        Args:
            path (Path): Candidate downloaded video file.

        Returns:
            tuple[int, str]: Sort key where merged files (no ``.f`` in the name) rank first.
        """
        looks_merged = ".f" not in path.name
        return (0 if looks_merged else 1, path.name)

    videos.sort(key=sort_key)
    return videos[0]
