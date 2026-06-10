from __future__ import annotations

from typing import Any

_VALID_LABELS = {"correct", "incorrect"}


def validate_feedback_submission(
    vid_id: str,
    label: str,
    comment: str = "",
) -> dict[str, Any]:
    """Validate analysis feedback without touching persistence.

    Returns:
        dict[str, Any]: ``{"status": "valid", "vid_id": ..., "label": ..., "comment": ...}``
        on success, or ``{"status": "missing_fields", "message": "empty feedback"}``.
    """
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

    return {
        "status": "valid",
        "vid_id": cleaned_vid_id,
        "label": cleaned_label,
        "comment": cleaned_comment or None,
    }
