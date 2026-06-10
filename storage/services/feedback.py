from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from storage.db.models import AnalysisFeedback, FeedbackLabel
from storage.db.sync_bridge import run_db_coroutine
from storage.schemas import FeedbackCreate


_VALID_LABELS = {member.value for member in FeedbackLabel}


def _normalize_label(label: str) -> FeedbackLabel | None:
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
    """Persist one analysis feedback record."""
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
    """Run feedback persistence on the shared database bridge."""
    try:
        return run_db_coroutine(_save_feedback_async(feedback_data))
    except Exception:
        return {
            "status": "storage_error",
            "message": "unable to save to storage",
        }
