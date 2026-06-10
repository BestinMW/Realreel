"""Unit tests for feedback persistence in the storage layer.

Database sessions are mocked — these tests run without a live Postgres connection.

Run:
    pytest tests/storage/test_feedback.py -v
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from storage.schemas import FeedbackCreate
from storage.services.feedback import (
    _save_feedback_async,
    save_feedback,
    save_feedback_sync,
)


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


# ---------------------------------------------------------------------------
# Test 3: save_feedback — rejects empty label
# ---------------------------------------------------------------------------
def test_save_feedback_rejects_empty_label():
    session = MagicMock()

    result = asyncio.run(
        save_feedback(
            session,
            FeedbackCreate(vid_id="example1", label="   ", comment=None),
        )
    )

    assert result["status"] == "storage_error"
    assert result["message"] == "unable to save to storage"
    session.add.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: save_feedback_sync — bridge success and failure paths
# ---------------------------------------------------------------------------
def _return_bridge_success(coro):
    coro.close()
    return {"status": "success", "id": "feedback-99"}


def test_save_feedback_sync_returns_success_from_bridge():
    with patch(
        "storage.services.feedback.run_db_coroutine",
        side_effect=_return_bridge_success,
    ):
        result = save_feedback_sync(
            FeedbackCreate(vid_id="example1", label="Correct", comment=None)
        )

    assert result["status"] == "success"
    assert result["id"] == "feedback-99"


def _raise_database_unavailable(coro):
    coro.close()
    raise RuntimeError("Database unavailable")


def test_save_feedback_sync_returns_storage_error_when_bridge_raises():
    with patch(
        "storage.services.feedback.run_db_coroutine",
        side_effect=_raise_database_unavailable,
    ):
        result = save_feedback_sync(
            FeedbackCreate(vid_id="example1", label="Incorrect", comment=None)
        )

    assert result["status"] == "storage_error"
    assert result["message"] == "unable to save to storage"


# ---------------------------------------------------------------------------
# Test 5: _save_feedback_async — empty bridge session
# ---------------------------------------------------------------------------
async def _empty_bridge_session():
    return
    yield MagicMock()


async def _bridge_session_with_session():
    session = MagicMock()
    session.commit = AsyncMock(return_value=None)
    yield session


def test_save_feedback_async_commits_when_save_succeeds():
    with (
        patch(
            "storage.db.sync_bridge.bridge_session",
            _bridge_session_with_session,
        ),
        patch(
            "storage.services.feedback.save_feedback",
            new=AsyncMock(return_value={"status": "success", "id": "feedback-42"}),
        ) as save_mock,
    ):
        result = asyncio.run(
            _save_feedback_async(
                FeedbackCreate(vid_id="example1", label="Correct", comment=None)
            )
        )

    assert result == {"status": "success", "id": "feedback-42"}
    save_mock.assert_awaited_once()


def test_save_feedback_async_returns_storage_error_when_bridge_yields_no_session():
    with patch(
        "storage.db.sync_bridge.bridge_session",
        _empty_bridge_session,
    ):
        result = asyncio.run(
            _save_feedback_async(
                FeedbackCreate(vid_id="example1", label="Correct", comment=None)
            )
        )

    assert result["status"] == "storage_error"
    assert result["message"] == "unable to save to storage"
