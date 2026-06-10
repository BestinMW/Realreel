"""Unit tests for adaptive frame sampling in the engine layer.

Run:
    pytest tests/engine/test_frame_sampling.py -v
"""

import pytest

from pipeline.media import compute_adaptive_frame_sample_rate


# ---------------------------------------------------------------------------
# Test 1: short videos sample more frequently than medium videos
# ---------------------------------------------------------------------------
def test_short_video_samples_more_frequently_than_medium_video():
    short_rate = compute_adaptive_frame_sample_rate(5)
    medium_rate = compute_adaptive_frame_sample_rate(60)
    assert short_rate > medium_rate


# ---------------------------------------------------------------------------
# Test 2: long videos sample less frequently than medium videos
# ---------------------------------------------------------------------------
def test_long_video_samples_less_frequently_than_medium_video():
    medium_rate = compute_adaptive_frame_sample_rate(60)
    long_rate = compute_adaptive_frame_sample_rate(3600)
    assert medium_rate > long_rate


# ---------------------------------------------------------------------------
# Test 3: frame budget stays within configured bounds
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("duration", [5, 30, 120, 900, 3600])
def test_frame_budget_stays_within_bounds(duration):
    rate = compute_adaptive_frame_sample_rate(duration)
    frame_count = duration * rate
    assert frame_count >= 8
    assert frame_count <= 60
