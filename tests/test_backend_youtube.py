import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pipeline.youtube import parse_video_url, parse_youtube_url, safe_segment  # noqa: E402


class VideoUrlParsingTests(unittest.TestCase):
    def test_parse_youtube_watch_shorts_embed_and_shortlink_urls(self) -> None:
        cases = {
            "https://www.youtube.com/watch?v=abc123XYZ_9": "abc123XYZ_9",
            "https://youtube.com/shorts/short-id": "short-id",
            "https://music.youtube.com/embed/embed-id": "embed-id",
            "https://youtu.be/shortlink-id?t=12": "shortlink-id",
        }

        for url, expected_id in cases.items():
            with self.subTest(url=url):
                self.assertEqual(parse_youtube_url(url), expected_id)
                self.assertEqual(parse_video_url(url)["platform"], "youtube")
                self.assertEqual(parse_video_url(url)["id"], expected_id)

    def test_parse_tiktok_instagram_and_direct_video_urls(self) -> None:
        self.assertEqual(
            parse_video_url("https://www.tiktok.com/@realreel/video/735"),
            {
                "platform": "tiktok",
                "id": "735",
                "url": "https://www.tiktok.com/@realreel/video/735",
            },
        )
        self.assertEqual(
            parse_video_url("https://www.instagram.com/reel/ABCdef123/")["id"],
            "ABCdef123",
        )
        self.assertEqual(
            parse_video_url("https://cdn.example.com/uploads/my clip.mp4"),
            {
                "platform": "direct",
                "id": "my_clip_mp4",
                "url": "https://cdn.example.com/uploads/my clip.mp4",
            },
        )

    def test_parse_video_url_rejects_non_http_and_unknown_inputs(self) -> None:
        for value in (None, "", "not a url", "ftp://example.com/video.mp4"):
            with self.subTest(value=value):
                self.assertIsNone(parse_video_url(value))

    def test_safe_segment_replaces_unsafe_filename_characters(self) -> None:
        self.assertEqual(safe_segment("video id/@2026!.mp4"), "video_id__2026__mp4")


if __name__ == "__main__":
    unittest.main()
