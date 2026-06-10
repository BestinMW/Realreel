from __future__ import annotations

from typing import Any

from pipeline.feedback import validate_feedback_submission
from storage.schemas import FeedbackCreate
from storage.services.feedback import save_feedback_sync


def submit_feedback(vid_id: str, label: str, comment: str = "") -> dict[str, Any]:
    """Validate feedback in the engine layer and persist it through storage."""
    validated = validate_feedback_submission(vid_id, label, comment)
    if validated["status"] != "valid":
        return validated

    save_result = save_feedback_sync(
        FeedbackCreate(
            vid_id=validated["vid_id"],
            label=validated["label"],
            comment=validated["comment"],
        )
    )

    if save_result.get("status") != "success":
        return {
            "status": "storage_error",
            "message": "feedback to storage failure",
        }

    return {
        "status": "success",
        "message": "feedback submitted",
    }
