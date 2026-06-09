import unittest

from pipeline.media import compute_adaptive_frame_sample_rate


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
