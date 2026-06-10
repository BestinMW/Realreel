"""Unit tests for analysis feedback submission in the engine layer.

The storage layer is mocked — these tests run without a live database.

Run:
    pytest tests/engine/test_feedback.py -v
"""

from unittest.mock import patch

from adapters.feedback import submit_feedback
from pipeline.feedback import validate_feedback_submission


# ---------------------------------------------------------------------------
# Test 1: validate_feedback_submission — missing required fields
# ---------------------------------------------------------------------------
def test_validate_feedback_submission_returns_empty_feedback_when_required_fields_missing():
    result = validate_feedback_submission("", "", "")
    assert result["status"] == "missing_fields"
    assert result["message"] == "empty feedback"


# ---------------------------------------------------------------------------
# Test 2: submit_feedback — storage failure
# ---------------------------------------------------------------------------
def test_submit_feedback_returns_storage_error_when_save_fails():
    with patch(
        "adapters.feedback.save_feedback_sync",
        return_value={"status": "storage_error", "message": "unable to save to storage"},
    ):
        result = submit_feedback("vid-1", "Incorrect", "too high")

    assert result["status"] == "storage_error"
    assert result["message"] == "feedback to storage failure"


# ---------------------------------------------------------------------------
# Test 3: submit_feedback — successful save
# ---------------------------------------------------------------------------
def test_submit_feedback_returns_success_when_save_succeeds():
    with patch(
        "adapters.feedback.save_feedback_sync",
        return_value={"status": "success", "id": "feedback-1"},
    ):
        result = submit_feedback(
            "vid-1",
            "Incorrect",
            "AI score is high when the video is clearly not AI.",
        )

    assert result["status"] == "success"
    assert result["message"] == "feedback submitted"
