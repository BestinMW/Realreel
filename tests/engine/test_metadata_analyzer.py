"""Unit tests for metadata analyzer rules in the engine layer.

Metadata collectors are mocked — these tests run without yt-dlp or ffprobe.

Run:
    pytest tests/engine/test_metadata_analyzer.py -v
"""

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.metadata_analyzer import CollectedMetadata, MetadataAnalyzer, RuleResult


def make_collected(
    *,
    platform: dict | None = None,
    video: dict | None = None,
    embedded_tags: dict | None = None,
    collection_errors: list[str] | None = None,
) -> CollectedMetadata:
    tags = embedded_tags or {}
    return CollectedMetadata(
        platform=platform or {},
        video=video or {},
        embedded=[tags] if tags else [],
        embedded_tags=tags,
        collection_errors=collection_errors or [],
    )


@pytest.fixture
def analyzer() -> MetadataAnalyzer:
    return MetadataAnalyzer(
        url="https://www.youtube.com/watch?v=test",
        video_path=Path("fake/source.mp4"),
    )


# ---------------------------------------------------------------------------
# Test 1: parse_date — common metadata date formats
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("20240115", date(2024, 1, 15)),
        ("2024-01-15", date(2024, 1, 15)),
        ("1/10/26", date(2026, 1, 10)),
        ("1/10/2026", date(2026, 1, 10)),
    ],
)
def test_parse_date_accepts_common_formats(value, expected):
    parsed = MetadataAnalyzer.parse_date(value)
    assert parsed is not None
    assert parsed.date() == expected


def test_parse_date_returns_none_for_invalid_input():
    assert MetadataAnalyzer.parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# Test 2: creation_date_conflict rule
# ---------------------------------------------------------------------------
def test_creation_date_conflict_flags_old_footage_with_recency_language(analyzer):
    old_date = (date.today() - timedelta(days=120)).strftime("%Y:%m:%d")
    collected = make_collected(embedded_tags={"QuickTime:CreateDate": old_date})

    result = analyzer._rule_creation_date_conflict("breaking news today", collected)

    assert result.flagged is True
    assert result.score == 0.9
    assert result.reason == "Video creation date predates claimed event."


def test_creation_date_conflict_not_flagged_without_recency_language(analyzer):
    old_date = (date.today() - timedelta(days=120)).strftime("%Y:%m:%d")
    collected = make_collected(embedded_tags={"QuickTime:CreateDate": old_date})

    result = analyzer._rule_creation_date_conflict("historical archive clip", collected)

    assert result.flagged is False


# ---------------------------------------------------------------------------
# Test 3: reencoded_edited and missing_metadata rules
# ---------------------------------------------------------------------------
def test_reencoded_edited_flags_editing_encoder(analyzer):
    collected = make_collected(
        embedded_tags={"QuickTime:CompressorName": "Adobe Premiere Pro"},
    )

    result = analyzer._rule_reencoded_edited(collected)

    assert result.flagged is True
    assert result.score == 0.2


def test_missing_metadata_flags_when_three_fields_absent(analyzer):
    result = analyzer._rule_missing_metadata(make_collected(embedded_tags={}))

    assert result.flagged is True
    assert result.score == 0.1


# ---------------------------------------------------------------------------
# Test 4: repost_age_mismatch rule
# ---------------------------------------------------------------------------
def test_repost_age_mismatch_flags_when_match_is_much_older(analyzer):
    collected = make_collected(platform={"upload_date": "20240601"})

    result = analyzer._rule_repost_age_mismatch(collected, "20230101")

    assert result.flagged is True
    assert result.score == 0.8


def test_repost_age_mismatch_not_flagged_without_match_date(analyzer):
    collected = make_collected(platform={"upload_date": "20240601"})

    result = analyzer._rule_repost_age_mismatch(collected, None)

    assert result.flagged is False


# ---------------------------------------------------------------------------
# Test 5: metadata_vs_claimed_source rule
# ---------------------------------------------------------------------------
def test_metadata_vs_claimed_source_flags_high_fps_with_cctv_claim(analyzer):
    collected = make_collected(
        video={"streams": [{"codec_type": "video", "avg_frame_rate": "60/1"}]}
    )

    result = analyzer._rule_metadata_vs_claimed_source(
        "leaked cctv surveillance footage",
        collected,
    )

    assert result.flagged is True
    assert result.score == 0.5


def test_metadata_vs_claimed_source_flags_edited_encoder_with_raw_claim(analyzer):
    collected = make_collected(
        embedded_tags={"QuickTime:Encoder": "Lavf (FFmpeg)"},
    )

    result = analyzer._rule_metadata_vs_claimed_source(
        "this is raw footage from a security camera",
        collected,
    )

    assert result.flagged is True


# ---------------------------------------------------------------------------
# Test 6: analyze — expected result shape
# ---------------------------------------------------------------------------
@patch("pipeline.metadata_analyzer.get_embedded_metadata")
@patch("pipeline.metadata_analyzer.get_video_metadata")
@patch("pipeline.metadata_analyzer.get_platform_metadata")
def test_analyze_returns_expected_shape(
    mock_platform, mock_video, mock_embedded, analyzer
):
    mock_platform.return_value = {"upload_date": "20240601", "title": "Test"}
    mock_video.return_value = {"format": {}, "streams": []}
    mock_embedded.return_value = [{}]

    result = analyzer.analyze(transcript_text="hello world")

    assert "metadata_score" in result
    assert "reasons" in result
    assert "rule_results" in result
    assert "collection_errors" in result
    assert isinstance(result["reasons"], list)
    assert set(result["rule_results"].keys()) == {
        "creation_date_conflict",
        "reencoded_edited",
        "missing_metadata",
        "repost_age_mismatch",
        "metadata_vs_claimed_source",
    }


@patch("pipeline.metadata_analyzer.get_embedded_metadata")
@patch("pipeline.metadata_analyzer.get_video_metadata")
@patch("pipeline.metadata_analyzer.get_platform_metadata")
def test_analyze_sums_scores_and_caps_at_one(
    mock_platform, mock_video, mock_embedded, analyzer
):
    old_date = (date.today() - timedelta(days=120)).strftime("%Y:%m:%d")
    mock_platform.return_value = {"upload_date": "20240601"}
    mock_video.return_value = {
        "streams": [{"codec_type": "video", "avg_frame_rate": "60/1"}]
    }
    mock_embedded.return_value = [
        {
            "QuickTime:CreateDate": old_date,
            "QuickTime:CompressorName": "Adobe Premiere Pro",
        }
    ]

    result = analyzer.analyze(
        transcript_text="breaking today from cctv raw footage",
        repost_match_date="20230101",
    )

    assert result["metadata_score"] == 1.0
    assert len(result["reasons"]) >= 2


@patch("pipeline.metadata_analyzer.get_embedded_metadata")
@patch("pipeline.metadata_analyzer.get_video_metadata")
@patch("pipeline.metadata_analyzer.get_platform_metadata")
def test_analyze_records_collection_errors_without_crashing(
    mock_platform, mock_video, mock_embedded, analyzer
):
    mock_platform.side_effect = RuntimeError("yt-dlp unavailable")
    mock_video.side_effect = RuntimeError("ffprobe missing")
    mock_embedded.side_effect = FileNotFoundError("exiftool missing")

    result = analyzer.analyze()

    assert len(result["collection_errors"]) == 3
    assert result["rule_results"]["missing_metadata"]["flagged"] is True


# ---------------------------------------------------------------------------
# Test 7: RuleResult.to_dict
# ---------------------------------------------------------------------------
def test_rule_result_to_dict():
    payload = RuleResult(
        flagged=True,
        score=0.9,
        reason="Video creation date predates claimed event.",
    ).to_dict()

    assert payload == {
        "flagged": True,
        "score": 0.9,
        "reason": "Video creation date predates claimed event.",
    }
