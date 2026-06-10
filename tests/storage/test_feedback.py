"""Unit tests for feedback persistence in the storage layer.

Database sessions are mocked — these tests run without a live Postgres connection.

Run:
    pytest tests/storage/test_feedback.py -v
"""

import asyncio
import uuid
from unittest.mock import MagicMock

from storage.schemas import FeedbackCreate
from storage.services.feedback import save_feedback


# ---------------------------------------------------------------------------
# Test 1: save_feedback — persists a valid record
# ---------------------------------------------------------------------------
def test_save_feedback_persists_record():
    session = MagicMock()
    added_record = None

    def capture_add(record) -> None:
        nonlocal added_record
        added_record = record
        record.id = uuid.uuid4()

    session.add = capture_add

    async def fake_flush() -> None:
        return None

    session.flush = fake_flush

    result = asyncio.run(
        save_feedback(
            session,
            FeedbackCreate(
                vid_id="example1",
                label="Incorrect",
                comment="AI score is high when the video is clearly not AI.",
            ),
        )
    )

    assert result["status"] == "success"
    assert uuid.UUID(result["id"])
    assert added_record is not None
    assert added_record.vid_id == "example1"


# ---------------------------------------------------------------------------
# Test 2: save_feedback — rejects invalid label
# ---------------------------------------------------------------------------
def test_save_feedback_rejects_invalid_label():
    session = MagicMock()

    result = asyncio.run(
        save_feedback(
            session,
            FeedbackCreate(vid_id="example1", label="Maybe", comment=None),
        )
    )

    assert result["status"] == "storage_error"
    session.add.assert_not_called()
