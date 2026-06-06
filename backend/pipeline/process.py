import json
import shutil
import time
import traceback
from collections.abc import Generator
from pathlib import Path

from .config import (
    FRAME_SAMPLE_RATE,
    KEYFRAME_SCENE_THRESHOLD,
    MAX_KEYFRAMES_TO_ANALYZE,
    STORAGE_BUCKETS,
    TRANSCRIPTION_LEAD_IN_SECONDS,
    UPLOADS_ROOT,
)
from .download import download_youtube_video
from .keyframes import analyze_keyframes_stream
from .media import (
    create_audio_with_lead_in,
    extract_audio,
    extract_keyframes,
    extract_sampled_frames,
    list_image_files,
)
from .storage import upload_to_supabase_storage
from .transcribe import transcribe_audio_with_openai
from .youtube import parse_youtube_url, safe_segment
from .metadata_analyzer import MetadataAnalyzer


def process_youtube_video(youtube_url: str) -> Generator[dict, None, None]:
    def send(event: dict) -> dict:
        return event

    job_dir: Path | None = None
    stage = "Starting"

    try:
        stage = "Reading request"
        yield send({"type": "progress", "progress": 3, "stage": stage})

        video_id = parse_youtube_url(youtube_url)
        if not video_id:
            yield send({"type": "error", "message": "Paste a valid YouTube video URL."})
            return

        job_id = f"{safe_segment(video_id)}-{int(time.time() * 1000)}"
        storage_prefix = f"videos/{job_id}"
        job_dir = UPLOADS_ROOT / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        audio_path = job_dir / "audio.wav"
        transcription_audio_path = job_dir / "audio-for-transcript.wav"
        transcript_path = job_dir / "transcript.json"
        keyframe_analysis_path = job_dir / "keyframe-analysis.json"
        frames_dir = job_dir / "frames"
        keyframes_dir = job_dir / "keyframes"
        frames_dir.mkdir(parents=True, exist_ok=True)
        keyframes_dir.mkdir(parents=True, exist_ok=True)

        stage = "Preparing workspace"
        yield send({"type": "progress", "progress": 8, "stage": stage})
        stage = "Preparing downloader"
        yield send({"type": "progress", "progress": 12, "stage": stage})
        stage = "Downloading video"
        yield send({"type": "progress", "progress": 18, "stage": stage})

        video_path = download_youtube_video(youtube_url, job_dir)

        stage = "Extracting audio"
        yield send({"type": "progress", "progress": 35, "stage": stage})
        extract_audio(video_path, audio_path)

        yield send(
            {
                "type": "progress",
                "progress": 43,
                "stage": "Preparing audio for transcription",
            }
        )
        create_audio_with_lead_in(audio_path, transcription_audio_path)

        yield send({"type": "progress", "progress": 50, "stage": "Extracting sampled frames"})
        extract_sampled_frames(video_path, frames_dir)

        yield send({"type": "progress", "progress": 56, "stage": "Extracting keyframes"})
        keyframe_timestamps = extract_keyframes(video_path, keyframes_dir)

        frame_paths = list_image_files(frames_dir)
        keyframe_paths = list_image_files(keyframes_dir)
        keyframes_for_analysis = keyframe_paths[:MAX_KEYFRAMES_TO_ANALYZE]
        timestamps_for_analysis = keyframe_timestamps[: len(keyframes_for_analysis)]

        video_suffix = video_path.suffix or ".mp4"
        raw_video_storage_path = f"{storage_prefix}/raw/original{video_suffix}"
        audio_storage_path = f"{storage_prefix}/audio/audio.wav"
        transcript_storage_path = f"{storage_prefix}/transcripts/transcript-und.json"
        keyframe_analysis_storage_path = (
            f"{storage_prefix}/analysis/keyframe-analysis.json"
        )

        yield send({"type": "progress", "progress": 62, "stage": "Transcribing audio"})
        transcript = transcribe_audio_with_openai(transcription_audio_path)
        transcript["source"] = {
            "youtubeUrl": youtube_url.strip(),
            "audioPath": audio_storage_path,
            "transcriptionLeadInSeconds": TRANSCRIPTION_LEAD_IN_SECONDS,
        }
        transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")

        yield send({"type": "progress", "progress": 70, "stage": "Analyzing keyframes"})

        keyframe_analysis = None
        for event in analyze_keyframes_stream(
            keyframe_paths=keyframes_for_analysis,
            keyframe_timestamps=timestamps_for_analysis,
            output_path=keyframe_analysis_path,
        ):
            if event.get("kind") == "progress":
                payload = event["payload"]
                index = payload.get("index", 0)
                total = max(payload.get("total", 1), 1)
                progress_value = 70 + round((index / total) * 8)
                yield send(
                    {
                        "type": "progress",
                        "progress": progress_value,
                        "stage": f"Analyzing keyframe {index} of {total}",
                    }
                )
            elif event.get("kind") == "result":
                keyframe_analysis = event["payload"]

        if keyframe_analysis is None:
            raise RuntimeError("Keyframe analysis did not complete.")

        yield send({"type": "progress", "progress": 82, "stage": "Uploading raw video"})
        upload_to_supabase_storage(
            bucket=STORAGE_BUCKETS["rawVideos"],
            storage_path=raw_video_storage_path,
            local_path=video_path,
            content_type="video/mp4",
        )

        yield send({"type": "progress", "progress": 88, "stage": "Uploading audio"})
        upload_to_supabase_storage(
            bucket=STORAGE_BUCKETS["audio"],
            storage_path=audio_storage_path,
            local_path=audio_path,
            content_type="audio/wav",
        )

        yield send({"type": "progress", "progress": 92, "stage": "Uploading transcript"})
        upload_to_supabase_storage(
            bucket=STORAGE_BUCKETS["transcripts"],
            storage_path=transcript_storage_path,
            local_path=transcript_path,
            content_type="application/json",
        )

        yield send(
            {"type": "progress", "progress": 95, "stage": "Uploading keyframe analysis"}
        )
        upload_to_supabase_storage(
            bucket=STORAGE_BUCKETS["analysis"],
            storage_path=keyframe_analysis_storage_path,
            local_path=keyframe_analysis_path,
            content_type="application/json",
        )

        yield send({"type": "progress", "progress": 97, "stage": "Cleaning temporary files"})
        shutil.rmtree(job_dir, ignore_errors=True)
        job_dir = None

        yield send(
            {
                "type": "complete",
                "progress": 100,
                "stage": "Complete",
                "result": {
                    "success": True,
                    "rawVideoPath": raw_video_storage_path,
                    "audioPath": audio_storage_path,
                    "transcriptPath": transcript_storage_path,
                    "keyframeAnalysisPath": keyframe_analysis_storage_path,
                    "transcriptText": transcript.get("text") or "",
                    "buckets": STORAGE_BUCKETS,
                    "frameCount": len(frame_paths),
                    "frameRate": FRAME_SAMPLE_RATE,
                    "keyFrameCount": len(keyframe_paths),
                    "analyzedKeyFrameCount": len(keyframes_for_analysis),
                    "maxKeyframesToAnalyze": MAX_KEYFRAMES_TO_ANALYZE,
                    "ocrTextFrameCount": sum(
                        1
                        for frame in keyframe_analysis["frames"]
                        if frame.get("ocr", {}).get("indicators", {}).get("hasText")
                    ),
                    "visionSignalFrameCount": sum(
                        1
                        for frame in keyframe_analysis["frames"]
                        if (frame.get("vision", {}).get("indicators", {}).get("contextSignals"))
                        or (
                            frame.get("vision", {})
                            .get("indicators", {})
                            .get("synthetic", {})
                            .get("signals")
                        )
                    ),
                    "crossModalHintCount": sum(
                        len(frame.get("hints") or [])
                        for frame in keyframe_analysis["frames"]
                    ),
                    "keyframeSceneThreshold": KEYFRAME_SCENE_THRESHOLD,
                    "message": (
                        "YouTube video processed. Raw video, audio, transcript, and "
                        "keyframe analysis were uploaded; local frames and keyframes "
                        "were deleted after processing."
                    ),
                },
            }
        )
        #   ADD ANALYSIS STARTING FROM HERE (METADATA ANALYZER, CLAIM ANALYZER, etc.)
        #   [change progress bar throughout to fit analysis stages]
        #
        #
        #
        #
        #
        #
        #
        #
        #
    except Exception as exc:
        message = str(exc) or "Failed to process YouTube video."
        print(f"[process-youtube] {stage} failed: {message}", flush=True)
        traceback.print_exc()
        yield send(
            {
                "type": "error",
                "message": f"{stage}: {message}",
            }
        )
    finally:
        if job_dir and job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
