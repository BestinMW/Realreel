from __future__ import annotations

from typing import Any

from storage.schemas import FeedbackCreate
from storage.services.feedback import save_feedback_sync

_VALID_LABELS = {"correct", "incorrect"}


def submit_feedback(vid_id: str, label: str, comment: str = "") -> dict[str, Any]:
    """Validate feedback and persist it."""
    cleaned_vid_id = (vid_id or "").strip()
    cleaned_label = (label or "").strip()
    cleaned_comment = (comment or "").strip()

    if not cleaned_vid_id and not cleaned_label:
        return {
            "status": "missing_fields",
            "message": "empty feedback",
        }

    if not cleaned_vid_id or not cleaned_label:
        return {
            "status": "missing_fields",
            "message": "empty feedback",
        }

    if cleaned_label.lower() not in _VALID_LABELS:
        return {
            "status": "missing_fields",
            "message": "empty feedback",
        }

    save_result = save_feedback_sync(
        FeedbackCreate(
            vid_id=cleaned_vid_id,
            label=cleaned_label,
            comment=cleaned_comment or None,
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
