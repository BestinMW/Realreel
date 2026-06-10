import hashlib
import re
import subprocess
from pathlib import Path

from .config import (
    ADAPTIVE_FRAME_SAMPLING,
    FRAME_SAMPLE_RATE,
    KEYFRAME_INTERVAL_SECONDS,
    KEYFRAME_SCENE_THRESHOLD,
    MAX_SAMPLED_FRAMES,
    MIN_SAMPLED_FRAMES,
    TARGET_SAMPLED_FRAMES,
    TRANSCRIPTION_LEAD_IN_SECONDS,
)
from .tools import get_ffmpeg_command


def compute_file_sha256(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file on disk.

    Args:
        path (Path): Path to the file to hash.

    Returns:
        str: Lowercase hexadecimal SHA-256 digest of the file contents.
    """
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_ffmpeg(args: list[str], capture_stderr: bool = False) -> str:
    """Run ffmpeg with the given arguments and fail on non-zero exit codes.

    Args:
        args (list[str]): ffmpeg arguments (without the executable or ``-y`` flag).
        capture_stderr (bool): When ``True``, return stderr text instead of an empty string.

    Returns:
        str: ffmpeg stderr when ``capture_stderr`` is ``True``; otherwise ``""``.

    Raises:
        RuntimeError: When ffmpeg is not found or exits with a non-zero status.
    """
    command = [*get_ffmpeg_command(), "-y", *args]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc
    if result.returncode != 0:
        stderr = result.stderr or result.stdout or "ffmpeg failed"
        raise RuntimeError(stderr.strip())
    return result.stderr if capture_stderr else ""


def probe_duration_seconds(video_path: Path) -> float:
    """Read a video file's duration from ffmpeg probe output.

    Args:
        video_path (Path): Path to the input video file.

    Returns:
        float: Duration in seconds parsed from ffmpeg metadata, or ``0.0`` when
            no ``Duration:`` field is found.
    """
    command = [*get_ffmpeg_command(), "-i", str(video_path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (result.stderr or "") + (result.stdout or "")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def extract_audio(video_path: Path, audio_path: Path) -> None:
    """Extract mono 16 kHz audio from a video, or synthesize silence if none exists.

    Args:
        video_path (Path): Path to the source video file.
        audio_path (Path): Output path for the generated WAV file.

    Returns:
        None
    """
    try:
        run_ffmpeg(
            [
                "-i",
                str(video_path),
                "-map",
                "0:a:0?",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(audio_path),
            ]
        )
        if audio_path.exists() and audio_path.stat().st_size > 0:
            return
    except RuntimeError:
        pass

    duration = max(probe_duration_seconds(video_path), 0.1)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=mono:sample_rate=16000",
            "-t",
            str(duration),
            "-ac",
            "1",
            str(audio_path),
        ]
    )


def create_audio_with_lead_in(source_path: Path, output_path: Path) -> None:
    """Prepend silent lead-in audio before an existing mono WAV for transcription.

    Args:
        source_path (Path): Path to the source mono audio WAV.
        output_path (Path): Output path for the concatenated WAV file.

    Returns:
        None
    """
    lead_in = TRANSCRIPTION_LEAD_IN_SECONDS
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-t",
            str(lead_in),
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=16000",
            "-i",
            str(source_path),
            "-filter_complex",
            "[0:a][1:a]concat=n=2:v=0:a=1[outa]",
            "-map",
            "[outa]",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]
    )


def compute_adaptive_frame_sample_rate(duration_seconds: float) -> float:
    """Choose an fps so sampled frame count scales with duration but stays bounded.

    Args:
        duration_seconds (float): Video duration in seconds.

    Returns:
        float: Frames-per-second sampling rate derived from configured min, max,
            and target frame counts.
    """
    duration = max(duration_seconds, 0.1)
    target_frames = max(1, TARGET_SAMPLED_FRAMES)
    min_frames = max(1, MIN_SAMPLED_FRAMES)
    max_frames = max(min_frames, MAX_SAMPLED_FRAMES)

    ideal_interval = duration / target_frames
    min_interval = duration / max_frames
    max_interval = duration / min_frames
    interval = max(min_interval, min(max_interval, ideal_interval))
    return 1.0 / interval


def resolve_frame_sample_rate(video_path: Path) -> float:
    """Resolve the frame sampling rate for a video.

    Args:
        video_path (Path): Path to the input video file.

    Returns:
        float: ``FRAME_SAMPLE_RATE`` when adaptive sampling is disabled or duration
            cannot be probed; otherwise the adaptive rate from
            ``compute_adaptive_frame_sample_rate``.
    """
    if not ADAPTIVE_FRAME_SAMPLING:
        return FRAME_SAMPLE_RATE

    duration = probe_duration_seconds(video_path)
    if duration <= 0:
        return FRAME_SAMPLE_RATE
    return compute_adaptive_frame_sample_rate(duration)


def extract_sampled_frames(video_path: Path, frames_dir: Path) -> float:
    """Extract uniformly sampled JPEG frames from a video.

    Args:
        video_path (Path): Path to the input video file.
        frames_dir (Path): Directory where ``frame_%05d.jpg`` files are written.

    Returns:
        float: Frames-per-second rate used for extraction and timestamp alignment.
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    sample_rate = resolve_frame_sample_rate(video_path)
    run_ffmpeg(
        [
            "-i",
            str(video_path),
            "-vf",
            f"fps={sample_rate}",
            "-q:v",
            "2",
            str(frames_dir / "frame_%05d.jpg"),
        ]
    )
    return sample_rate


def extract_keyframes(video_path: Path, keyframes_dir: Path) -> list[float]:
    """Extract scene-change keyframe JPEGs and collect their timestamps.

    Args:
        video_path (Path): Path to the input video file.
        keyframes_dir (Path): Directory where ``keyframe_%05d.jpg`` files are written.

    Returns:
        list[float]: Presentation timestamps in seconds parsed from ffmpeg
            ``showinfo`` stderr, in extraction order.
    """
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    interval = max(KEYFRAME_INTERVAL_SECONDS, 0.1)
    stderr = run_ffmpeg(
        [
            "-i",
            str(video_path),
            "-vf",
            (
                "select="
                f"eq(n\\,0)+gt(scene\\,{KEYFRAME_SCENE_THRESHOLD})+"
                f"gte(t-prev_selected_t\\,{interval}),showinfo"
            ),
            "-vsync",
            "vfr",
            "-q:v",
            "2",
            str(keyframes_dir / "keyframe_%05d.jpg"),
        ],
        capture_stderr=True,
    )
    return [float(match.group(1)) for match in re.finditer(r"pts_time:([0-9.]+)", stderr)]


def list_image_files(directory: Path) -> list[Path]:
    """List non-hidden files in a directory sorted by name.

    Args:
        directory (Path): Directory to scan for image files.

    Returns:
        list[Path]: Sorted file paths in ``directory``; ``[]`` when the directory
            does not exist.
    """
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )
