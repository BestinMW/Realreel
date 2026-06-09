import sys
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(TimeoutException=TimeoutError)

from pipeline import visual_events  # noqa: E402


class VisualEventSelectionTests(unittest.TestCase):
    def test_even_fallback_uses_limited_frame_count_for_normal_videos(self) -> None:
        frame_paths = [Path(f"frame_{index:05d}.jpg") for index in range(120)]

        selected = visual_events._select_event_frames(
            frame_paths=frame_paths,
            temporal_analysis={"comparisons": []},
            limit=6,
            window_radius=2,
        )

        self.assertEqual(len(selected), visual_events.MAX_VISUAL_EVENT_FALLBACK_FRAMES)
        self.assertEqual({frame["reason"] for frame in selected}, {"even_sample_fallback"})

    def test_suspicious_temporal_window_can_use_full_analysis_limit(self) -> None:
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

        self.assertEqual(len(selected), 5)
        self.assertEqual(
            {frame["reason"] for frame in selected},
            {"suspicious_temporal_window"},
        )


if __name__ == "__main__":
    unittest.main()
