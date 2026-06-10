from __future__ import annotations

import uuid
from pathlib import Path


def video_prefix(video_id: uuid.UUID) -> str:
    """Return the root storage prefix for one analyzed video.

    Args:
        video_id (uuid.UUID): Saved video primary key.

    Returns:
        str: Prefix of the form ``videos/{video_id}``.
    """
    return f"videos/{video_id}"


def raw_video_path(video_id: uuid.UUID, filename: str) -> str:
    """Build the Supabase path for a raw uploaded video artifact.

    Args:
        video_id (uuid.UUID): Saved video primary key.
        filename (str): Source filename used to infer the file extension.

    Returns:
        str: Object path within the raw-videos bucket (streamed as ``rawVideoPath``).
    """
    return f"{video_prefix(video_id)}/raw/original{_extension(filename, default='.mp4')}"


def audio_path(video_id: uuid.UUID) -> str:
    """Build the Supabase path for extracted audio (``audioPath`` in analysis results).

    Args:
        video_id (uuid.UUID): Saved video primary key.

    Returns:
        str: Object path within the audio bucket.
    """
    return f"{video_prefix(video_id)}/audio/audio.wav"


def transcript_path(video_id: uuid.UUID, language: str = "und") -> str:
    """Build the Supabase path for a transcript JSON artifact (``transcriptPath``).

    Args:
        video_id (uuid.UUID): Saved video primary key.
        language (str): BCP-47 or platform language code embedded in the filename.

    Returns:
        str: Object path within the transcripts bucket.
    """
    return f"{video_prefix(video_id)}/transcripts/transcript-{language}.json"


def thumbnail_path(video_id: uuid.UUID) -> str:
    """Build the Supabase path for a thumbnail image (``thumbnailPath``).

    Args:
        video_id (uuid.UUID): Saved video primary key.

    Returns:
        str: Object path within the thumbnails bucket.
    """
    return f"{video_prefix(video_id)}/thumbnails/thumbnail.jpg"


def _extension(filename: str, default: str) -> str:
    suffix = Path(filename).suffix
    return suffix if suffix else default
