import re
import subprocess
from pathlib import Path

from .config import FRAME_SAMPLE_RATE, KEYFRAME_SCENE_THRESHOLD, TRANSCRIPTION_LEAD_IN_SECONDS
from .tools import get_ffmpeg_command


def run_ffmpeg(args: list[str], capture_stderr: bool = False) -> str:
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
    command = [*get_ffmpeg_command(), "-i", str(video_path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (result.stderr or "") + (result.stdout or "")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def extract_audio(video_path: Path, audio_path: Path) -> None:
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


def extract_sampled_frames(video_path: Path, frames_dir: Path) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-i",
            str(video_path),
            "-vf",
            f"fps={FRAME_SAMPLE_RATE}",
            "-q:v",
            "2",
            str(frames_dir / "frame_%05d.jpg"),
        ]
    )


def extract_keyframes(video_path: Path, keyframes_dir: Path) -> list[float]:
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    stderr = run_ffmpeg(
        [
            "-i",
            str(video_path),
            "-vf",
            f"select=eq(n\\,0)+gt(scene\\,{KEYFRAME_SCENE_THRESHOLD}),showinfo",
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
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )
