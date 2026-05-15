from __future__ import annotations

import enum
import uuid
from pathlib import Path

from storage.core.config import settings


class StorageBucket(str, enum.Enum):
    RAW_VIDEOS = "raw-videos"
    AUDIO = "audio"
    TRANSCRIPTS = "transcripts"
    THUMBNAILS = "thumbnails"


BUCKET_NAMES: dict[StorageBucket, str] = {
    StorageBucket.RAW_VIDEOS: settings.raw_videos_bucket,
    StorageBucket.AUDIO: settings.audio_bucket,
    StorageBucket.TRANSCRIPTS: settings.transcripts_bucket,
    StorageBucket.THUMBNAILS: settings.thumbnails_bucket,
}


def video_prefix(video_id: uuid.UUID) -> str:
    return f"videos/{video_id}"


def raw_video_path(video_id: uuid.UUID, filename: str) -> str:
    return f"{video_prefix(video_id)}/raw/original{_extension(filename, default='.mp4')}"


def audio_path(video_id: uuid.UUID) -> str:
    return f"{video_prefix(video_id)}/audio/audio.wav"


def transcript_path(video_id: uuid.UUID, language: str = "und") -> str:
    return f"{video_prefix(video_id)}/transcripts/transcript-{language}.json"


def thumbnail_path(video_id: uuid.UUID) -> str:
    return f"{video_prefix(video_id)}/thumbnails/thumbnail.jpg"


def all_asset_prefixes(video_id: uuid.UUID) -> dict[StorageBucket, list[str]]:
    base = video_prefix(video_id)
    return {
        StorageBucket.RAW_VIDEOS: [f"{base}/raw/"],
        StorageBucket.AUDIO: [f"{base}/audio/"],
        StorageBucket.TRANSCRIPTS: [f"{base}/transcripts/"],
        StorageBucket.THUMBNAILS: [f"{base}/thumbnails/"],
    }


def _extension(filename: str, default: str) -> str:
    suffix = Path(filename).suffix
    return suffix if suffix else default
