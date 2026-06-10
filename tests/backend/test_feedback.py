from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

from pipeline.feedback import submit_feedback  # noqa: E402


class SubmitFeedbackTests(unittest.TestCase):
    def test_empty_feedback_when_required_fields_missing(self) -> None:
        result = submit_feedback("", "", "")
        self.assertEqual(result["status"], "missing_fields")
        self.assertEqual(result["message"], "empty feedback")

    def test_storage_error_when_save_fails(self) -> None:
        with patch(
            "pipeline.feedback.save_feedback_sync",
            return_value={"status": "storage_error", "message": "unable to save to storage"},
        ):
            result = submit_feedback("vid-1", "Incorrect", "too high")
        self.assertEqual(result["status"], "storage_error")
        self.assertEqual(result["message"], "feedback to storage failure")

    def test_success_saves_feedback(self) -> None:
        with patch(
            "pipeline.feedback.save_feedback_sync",
            return_value={"status": "success", "id": "feedback-1"},
        ):
            result = submit_feedback(
                "vid-1",
                "Incorrect",
                "AI score is high when the video is clearly not AI.",
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["message"], "feedback submitted")


if __name__ == "__main__":
    unittest.main()
