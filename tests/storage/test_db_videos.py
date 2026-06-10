"""Unit tests for database video payload mapping in the storage layer.

Run:
    pytest tests/storage/test_db_videos.py -v
"""

from decimal import Decimal

from storage.services.db_videos import build_db_video_payload, compute_overall_risk_score


# ---------------------------------------------------------------------------
# Test 1: compute_overall_risk_score — uses highest input risk
# ---------------------------------------------------------------------------
def test_compute_overall_risk_score_uses_highest_input():
    assert (
        compute_overall_risk_score(
            misleading_probability=0.2,
            visual_authenticity_risk=0.7,
            thumbnail_clickbait_score=0.1,
            repost_risk=0.4,
        )
        == 0.7
    )


# ---------------------------------------------------------------------------
# Test 2: build_db_video_payload — maps scores and artifact paths
# ---------------------------------------------------------------------------
def test_build_db_video_payload_maps_scores_and_paths():
    payload = build_db_video_payload(
        original_url="https://www.youtube.com/watch?v=abc123",
        platform="youtube",
        file_sha256="a" * 64,
        download_info={
            "title": "Test video",
            "duration": 42.5,
            "uploader_id": "channel",
            "upload_date": "20240615",
        },
        transcript_text="hello world",
        raw_video_path="videos/youtube/job/raw/original.mp4",
        thumbnail_path="videos/youtube/job/thumbnails/thumbnail.jpg",
        transcript_path="videos/youtube/job/transcripts/transcript-und.json",
        claim_analysis={
            "misleadingProbability": 0.3,
            "visualAuthenticityRisk": 0.8,
            "confidence": 0.9,
            "verdict": "mixed",
            "summary": "Summary",
            "recommendedAction": "flag_for_review",
        },
        thumbnail_clickbait_analysis={"clickbaitScore": 0.25},
        metadata_analysis={"metadata_score": 0.1},
        repost_result={"isRepost": False, "repostProbability": 0.0},
        repost_risk=None,
        analysis_paths={
            "claimAnalysis": "videos/youtube/job/analysis/claim-analysis.json"
        },
    )

    assert payload.platform.value == "youtube"
    assert payload.file_sha256 == "a" * 64
    assert payload.ai_generated_score == Decimal("0.8000")
    assert payload.misleading_context_score == Decimal("0.3000")
    assert payload.overall_risk_score == Decimal("0.8000")
    assert payload.credibility_score == Decimal("0.2000")
    assert payload.platform_upload_date.isoformat() == "2024-06-15"
    assert (
        payload.reasons["analysisPaths"]["claimAnalysis"]
        == "videos/youtube/job/analysis/claim-analysis.json"
    )
