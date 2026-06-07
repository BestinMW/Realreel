from __future__ import annotations

import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class ParseDateTests(unittest.TestCase):
    def test_parse_yyyymmdd(self) -> None:
        parsed = MetadataAnalyzer.parse_date("20240115")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.date(), date(2024, 1, 15))

    def test_parse_iso_date(self) -> None:
        parsed = MetadataAnalyzer.parse_date("2024-01-15")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.date(), date(2024, 1, 15))

    def test_parse_slash_date_mdy_two_digit_year(self) -> None:
        parsed = MetadataAnalyzer.parse_date("1/10/26")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.date(), date(2026, 1, 10))

    def test_parse_slash_date_mdy_four_digit_year(self) -> None:
        parsed = MetadataAnalyzer.parse_date("1/10/2026")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.date(), date(2026, 1, 10))

    def test_parse_invalid_returns_none(self) -> None:
        self.assertIsNone(MetadataAnalyzer.parse_date("not-a-date"))


class RuleUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = MetadataAnalyzer(
            url="https://www.youtube.com/watch?v=test",
            video_path=Path("fake/source.mp4"),
        )

    def test_creation_date_conflict_flags_old_footage_with_recency_language(self) -> None:
        old_date = (date.today() - timedelta(days=120)).strftime("%Y:%m:%d")
        collected = make_collected(
            embedded_tags={"QuickTime:CreateDate": old_date},
        )

        result = self.analyzer._rule_creation_date_conflict(
            "breaking news today",
            collected,
        )

        self.assertTrue(result.flagged)
        self.assertEqual(result.score, 0.9)
        self.assertEqual(result.reason, "Video creation date predates claimed event.")

    def test_creation_date_conflict_not_flagged_without_recency_language(self) -> None:
        old_date = (date.today() - timedelta(days=120)).strftime("%Y:%m:%d")
        collected = make_collected(
            embedded_tags={"QuickTime:CreateDate": old_date},
        )

        result = self.analyzer._rule_creation_date_conflict(
            "historical archive clip",
            collected,
        )

        self.assertFalse(result.flagged)

    def test_reencoded_edited_flags_editing_encoder(self) -> None:
        collected = make_collected(
            embedded_tags={"QuickTime:CompressorName": "Adobe Premiere Pro"},
        )

        result = self.analyzer._rule_reencoded_edited(collected)

        self.assertTrue(result.flagged)
        self.assertEqual(result.score, 0.2)

    def test_missing_metadata_flags_when_three_fields_absent(self) -> None:
        collected = make_collected(embedded_tags={})

        result = self.analyzer._rule_missing_metadata(collected)

        self.assertTrue(result.flagged)
        self.assertEqual(result.score, 0.1)

    def test_repost_age_mismatch_flags_when_match_is_much_older(self) -> None:
        collected = make_collected(platform={"upload_date": "20240601"})

        result = self.analyzer._rule_repost_age_mismatch(collected, "20230101")

        self.assertTrue(result.flagged)
        self.assertEqual(result.score, 0.8)

    def test_repost_age_mismatch_not_flagged_without_match_date(self) -> None:
        collected = make_collected(platform={"upload_date": "20240601"})

        result = self.analyzer._rule_repost_age_mismatch(collected, None)

        self.assertFalse(result.flagged)

    def test_metadata_vs_claimed_source_flags_high_fps_with_cctv_claim(self) -> None:
        collected = make_collected(
            video={
                "streams": [
                    {
                        "codec_type": "video",
                        "avg_frame_rate": "60/1",
                    }
                ]
            }
        )

        result = self.analyzer._rule_metadata_vs_claimed_source(
            "leaked cctv surveillance footage",
            collected,
        )

        self.assertTrue(result.flagged)
        self.assertEqual(result.score, 0.5)

    def test_metadata_vs_claimed_source_flags_edited_encoder_with_raw_claim(self) -> None:
        collected = make_collected(
            embedded_tags={"QuickTime:Encoder": "Lavf (FFmpeg)"},
        )

        result = self.analyzer._rule_metadata_vs_claimed_source(
            "this is raw footage from a security camera",
            collected,
        )

        self.assertTrue(result.flagged)


class AnalyzeIntegrationTests(unittest.TestCase):
    @patch("pipeline.metadata_analyzer.get_embedded_metadata")
    @patch("pipeline.metadata_analyzer.get_video_metadata")
    @patch("pipeline.metadata_analyzer.get_platform_metadata")
    def test_analyze_returns_expected_shape(
        self,
        mock_platform: MagicMock,
        mock_video: MagicMock,
        mock_embedded: MagicMock,
    ) -> None:
        mock_platform.return_value = {"upload_date": "20240601", "title": "Test"}
        mock_video.return_value = {"format": {}, "streams": []}
        mock_embedded.return_value = [{}]

        analyzer = MetadataAnalyzer(
            url="https://www.youtube.com/watch?v=test",
            video_path=Path("fake/source.mp4"),
        )
        result = analyzer.analyze(transcript_text="hello world")

        self.assertIn("metadata_score", result)
        self.assertIn("reasons", result)
        self.assertIn("rule_results", result)
        self.assertIn("collection_errors", result)
        self.assertIsInstance(result["reasons"], list)
        self.assertEqual(
            set(result["rule_results"].keys()),
            {
                "creation_date_conflict",
                "reencoded_edited",
                "missing_metadata",
                "repost_age_mismatch",
                "metadata_vs_claimed_source",
            },
        )

    @patch("pipeline.metadata_analyzer.get_embedded_metadata")
    @patch("pipeline.metadata_analyzer.get_video_metadata")
    @patch("pipeline.metadata_analyzer.get_platform_metadata")
    def test_analyze_sums_scores_and_caps_at_one(
        self,
        mock_platform: MagicMock,
        mock_video: MagicMock,
        mock_embedded: MagicMock,
    ) -> None:
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

        analyzer = MetadataAnalyzer(
            url="https://www.youtube.com/watch?v=test",
            video_path=Path("fake/source.mp4"),
        )
        result = analyzer.analyze(
            transcript_text="breaking today from cctv raw footage",
            repost_match_date="20230101",
        )

        self.assertEqual(result["metadata_score"], 1.0)
        self.assertGreaterEqual(len(result["reasons"]), 2)

    @patch("pipeline.metadata_analyzer.get_embedded_metadata")
    @patch("pipeline.metadata_analyzer.get_video_metadata")
    @patch("pipeline.metadata_analyzer.get_platform_metadata")
    def test_analyze_records_collection_errors_without_crashing(
        self,
        mock_platform: MagicMock,
        mock_video: MagicMock,
        mock_embedded: MagicMock,
    ) -> None:
        mock_platform.side_effect = RuntimeError("yt-dlp unavailable")
        mock_video.side_effect = RuntimeError("ffprobe missing")
        mock_embedded.side_effect = FileNotFoundError("exiftool missing")

        analyzer = MetadataAnalyzer(
            url="https://www.youtube.com/watch?v=test",
            video_path=Path("fake/source.mp4"),
        )
        result = analyzer.analyze()

        self.assertEqual(len(result["collection_errors"]), 3)
        self.assertTrue(result["rule_results"]["missing_metadata"]["flagged"])


class RuleResultTests(unittest.TestCase):
    def test_rule_result_to_dict(self) -> None:
        payload = RuleResult(
            flagged=True,
            score=0.9,
            reason="Video creation date predates claimed event.",
        ).to_dict()

        self.assertEqual(
            payload,
            {
                "flagged": True,
                "score": 0.9,
                "reason": "Video creation date predates claimed event.",
            },
        )


if __name__ == "__main__":
    unittest.main()
