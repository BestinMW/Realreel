"""Unit tests for storage schemas, paths, and repost payload merging.

Run:
    pytest tests/storage/test_pipeline_units.py -v
"""

import uuid
from decimal import Decimal

import pytest

from storage.assets.paths import audio_path, raw_video_path, thumbnail_path, transcript_path
from storage.db.models import Platform
from storage.schemas import VideoCreate
from storage.services.reposts import apply_repost_assessment_to_payload
from storage.vector import validate_embedding


# ---------------------------------------------------------------------------
# Test 1: VideoCreate — validates a complete payload
# ---------------------------------------------------------------------------
def test_video_payload_validates():
    payload = VideoCreate(
        original_url="https://www.youtube.com/watch?v=test-video",
        platform=Platform.YOUTUBE,
        title="Test video",
        raw_video_path="videos/test/raw/original.mp4",
        thumbnail_path="videos/test/thumbnails/thumbnail.jpg",
        transcript_text="This is a test transcript.",
        duration_seconds=Decimal("12.5"),
        file_sha256="a" * 64,
        video_embedding=[0.01] * 512,
        embedding_model="test-embedding-model",
        ai_generated_score=Decimal("0.1000"),
        misleading_context_score=Decimal("0.2000"),
        repost_probability=Decimal("0.3000"),
        credibility_score=Decimal("0.8000"),
        overall_risk_score=Decimal("0.2500"),
        confidence=Decimal("0.9000"),
        reasons={"summary": "Unit test payload."},
    )

    assert payload.platform == Platform.YOUTUBE
    assert len(payload.video_embedding or []) == 512


# ---------------------------------------------------------------------------
# Test 2: storage paths — deterministic per video id
# ---------------------------------------------------------------------------
def test_storage_paths_are_deterministic():
    video_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

    assert (
        raw_video_path(video_id, "clip.mp4")
        == "videos/00000000-0000-0000-0000-000000000001/raw/original.mp4"
    )
    assert (
        audio_path(video_id)
        == "videos/00000000-0000-0000-0000-000000000001/audio/audio.wav"
    )
    assert (
        thumbnail_path(video_id)
        == "videos/00000000-0000-0000-0000-000000000001/thumbnails/thumbnail.jpg"
    )
    assert (
        transcript_path(video_id, "en")
        == "videos/00000000-0000-0000-0000-000000000001/transcripts/transcript-en.json"
    )


# ---------------------------------------------------------------------------
# Test 3: validate_embedding — checks configured dimension
# ---------------------------------------------------------------------------
def test_embedding_dimension_is_checked():
    validate_embedding([0.0] * 512)

    with pytest.raises(ValueError):
        validate_embedding([0.0] * 3)


# ---------------------------------------------------------------------------
# Test 4: apply_repost_assessment_to_payload — raises misleading context
# ---------------------------------------------------------------------------
def test_repost_assessment_flags_misleading_context():
    payload_data = {
        "repost_probability": Decimal("0.1000"),
        "misleading_context_score": Decimal("0.2000"),
        "overall_risk_score": Decimal("0.3000"),
        "reasons": {"summary": "Existing analysis."},
    }
    assessment = {
        "isRepost": True,
        "repostProbability": Decimal("0.9200"),
        "matches": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "originalUrl": "https://example.com/older-video.mp4",
                "similarity": 0.94,
                "createdAt": "2024-01-01T00:00:00+00:00",
            }
        ],
        "rationale": "Closest saved video is 94% similar.",
    }

    merged = apply_repost_assessment_to_payload(payload_data, assessment)

    assert merged["repost_probability"] == Decimal("0.9200")
    assert merged["misleading_context_score"] == Decimal("0.6500")
    assert merged["overall_risk_score"] == Decimal("0.6500")
    assert "possible_repost" in merged["reasons"]["flags"]
    assert merged["reasons"]["repost"]["matches"][0]["similarity"] == 0.94
