"""Unit tests for visual event frame selection in the engine layer.

Run:
    pytest tests/engine/test_visual_event_selection.py -v
"""

from pathlib import Path

from pipeline import visual_events


# ---------------------------------------------------------------------------
# Test 1: even fallback — limited frame count for normal videos
# ---------------------------------------------------------------------------
def test_even_fallback_uses_limited_frame_count_for_normal_videos():
    frame_paths = [Path(f"frame_{index:05d}.jpg") for index in range(120)]

    selected = visual_events._select_event_frames(
        frame_paths=frame_paths,
        temporal_analysis={"comparisons": []},
        limit=6,
        window_radius=2,
    )

    assert len(selected) == visual_events.MAX_VISUAL_EVENT_FALLBACK_FRAMES
    assert {frame["reason"] for frame in selected} == {"even_sample_fallback"}


# ---------------------------------------------------------------------------
# Test 2: suspicious temporal window — uses full analysis limit
# ---------------------------------------------------------------------------
def test_suspicious_temporal_window_can_use_full_analysis_limit():
    frame_paths = [Path(f"frame_{index:05d}.jpg") for index in range(10)]
    temporal_analysis = {
        "comparisons": [
            {
                "fromFrame": "frame_00004.jpg",
                "toFrame": "frame_00005.jpg",
                "riskSignals": ["large_visual_change_without_scene_cut"],
                "instabilityScore": 0.9,
            }
        ]
    }

    selected = visual_events._select_event_frames(
        frame_paths=frame_paths,
        temporal_analysis=temporal_analysis,
        limit=5,
        window_radius=2,
    )

    assert len(selected) == 5
    assert {frame["reason"] for frame in selected} == {"suspicious_temporal_window"}
