import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from pipeline.media import compute_adaptive_frame_sample_rate  # noqa: E402


class AdaptiveFrameSamplingTests(unittest.TestCase):
    def test_short_video_samples_more_frequently(self) -> None:
        short_rate = compute_adaptive_frame_sample_rate(5)
        medium_rate = compute_adaptive_frame_sample_rate(60)
        self.assertGreater(short_rate, medium_rate)

    def test_long_video_samples_less_frequently(self) -> None:
        medium_rate = compute_adaptive_frame_sample_rate(60)
        long_rate = compute_adaptive_frame_sample_rate(3600)
        self.assertGreater(medium_rate, long_rate)

    def test_frame_budget_stays_within_bounds(self) -> None:
        for duration in (5, 30, 120, 900, 3600):
            rate = compute_adaptive_frame_sample_rate(duration)
            frame_count = duration * rate
            self.assertGreaterEqual(frame_count, 8)
            self.assertLessEqual(frame_count, 60)


if __name__ == "__main__":
    unittest.main()
