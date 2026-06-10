from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from storage.db.models import AnalysisFeedback, FeedbackLabel
from storage.db.sync_bridge import run_db_coroutine
from storage.schemas import FeedbackCreate


_VALID_LABELS = {member.value for member in FeedbackLabel}


def _normalize_label(label: str) -> FeedbackLabel | None:
    """Map a user-supplied label string to a ``FeedbackLabel`` enum member.

    Args:
        label (str): Raw label from the feedback payload (e.g. ``Correct``, ``Incorrect``).

    Returns:
        FeedbackLabel | None: The matching enum member, or ``None`` when the label is empty
        or not ``Correct`` / ``Incorrect``.
    """
    cleaned = label.strip()
    if not cleaned:
        return None

    for member in FeedbackLabel:
        if cleaned.lower() == member.value.lower():
            return member
    return None


async def save_feedback(
    session: AsyncSession,
    feedback_data: FeedbackCreate,
) -> dict[str, Any]:
    """Persist one analysis feedback record to ``public.analysis_feedback``.

    Args:
        session (AsyncSession): Active SQLAlchemy async database session.
        feedback_data (FeedbackCreate): Payload with ``vid_id``, ``label``, and optional
            ``comment`` (e.g. ``{"vid_id": "example1", "label": "Incorrect",
            "comment": "AI score is high when the video is clearly not AI."}``).

    Returns:
        dict[str, Any]: On success, ``{"status": "success", "id": "<feedback-uuid>"}``.
        On invalid label or persistence failure,
        ``{"status": "storage_error", "message": "unable to save to storage"}``.
    """
    label = _normalize_label(feedback_data.label)
    if label is None:
        return {
            "status": "storage_error",
            "message": "unable to save to storage",
        }

    record = AnalysisFeedback(
        vid_id=feedback_data.vid_id.strip(),
        label=label,
        comment=(feedback_data.comment or "").strip() or None,
    )
    session.add(record)
    await session.flush()
    return {
        "status": "success",
        "id": str(record.id),
    }


async def _save_feedback_async(feedback_data: FeedbackCreate) -> dict[str, Any]:
    """Open a bridge session, save feedback, and commit on success.

    Args:
        feedback_data (FeedbackCreate): Feedback payload passed to ``save_feedback``.

    Returns:
        dict[str, Any]: Same contract as ``save_feedback`` — ``{"status": "success",
        "id": "<feedback-uuid>"}`` or
        ``{"status": "storage_error", "message": "unable to save to storage"}``.
    """
    from storage.db.sync_bridge import bridge_session

    async for session in bridge_session():
        result = await save_feedback(session, feedback_data)
        if result["status"] == "success":
            await session.commit()
        return result

    return {
        "status": "storage_error",
        "message": "unable to save to storage",
    }


def save_feedback_sync(feedback_data: FeedbackCreate) -> dict[str, Any]:
    """Run feedback persistence on the shared database bridge from synchronous callers.

    Args:
        feedback_data (FeedbackCreate): Feedback payload with ``vid_id``, ``label``, and
            optional ``comment``.

    Returns:
        dict[str, Any]: On success, ``{"status": "success", "id": "<feedback-uuid>"}``.
        On database or bridge failure,
        ``{"status": "storage_error", "message": "unable to save to storage"}``.
    """
    try:
        return run_db_coroutine(_save_feedback_async(feedback_data))
    except Exception:
        return {
            "status": "storage_error",
            "message": "unable to save to storage",
        }
