"""Unit tests for video URL parsing in the engine layer.

Run:
    pytest tests/engine/test_backend_youtube.py -v
"""

import pytest

from pipeline.youtube import parse_video_url, parse_youtube_url, safe_segment


# ---------------------------------------------------------------------------
# Test 1: parse_youtube_url — common YouTube URL formats
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("url", "expected_id"),
    [
        ("https://www.youtube.com/watch?v=abc123XYZ_9", "abc123XYZ_9"),
        ("https://youtube.com/shorts/short-id", "short-id"),
        ("https://music.youtube.com/embed/embed-id", "embed-id"),
        ("https://youtu.be/shortlink-id?t=12", "shortlink-id"),
    ],
)
def test_parse_youtube_urls_extract_expected_video_id(url, expected_id):
    assert parse_youtube_url(url) == expected_id
    parsed = parse_video_url(url)
    assert parsed["platform"] == "youtube"
    assert parsed["id"] == expected_id


# ---------------------------------------------------------------------------
# Test 2: parse_video_url — TikTok, Instagram, and direct links
# ---------------------------------------------------------------------------
def test_parse_video_url_handles_tiktok_instagram_and_direct_links():
    assert parse_video_url("https://www.tiktok.com/@realreel/video/735") == {
        "platform": "tiktok",
        "id": "735",
        "url": "https://www.tiktok.com/@realreel/video/735",
    }
    assert (
        parse_video_url("https://www.instagram.com/reel/ABCdef123/")["id"]
        == "ABCdef123"
    )
    assert parse_video_url("https://cdn.example.com/uploads/my clip.mp4") == {
        "platform": "direct",
        "id": "my_clip_mp4",
        "url": "https://cdn.example.com/uploads/my clip.mp4",
    }


# ---------------------------------------------------------------------------
# Test 3: parse_video_url — rejects invalid inputs
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    [None, "", "not a url", "ftp://example.com/video.mp4"],
)
def test_parse_video_url_rejects_non_http_and_unknown_inputs(value):
    assert parse_video_url(value) is None


# ---------------------------------------------------------------------------
# Test 4: safe_segment — sanitizes unsafe filename characters
# ---------------------------------------------------------------------------
def test_safe_segment_replaces_unsafe_filename_characters():
    assert safe_segment("video id/@2026!.mp4") == "video_id__2026__mp4"
