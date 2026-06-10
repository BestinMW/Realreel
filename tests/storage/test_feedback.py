from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")

from storage.schemas import FeedbackCreate  # noqa: E402
from storage.services.feedback import save_feedback  # noqa: E402


class SaveFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_save_feedback_persists_record(self) -> None:
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

        result = await save_feedback(
            session,
            FeedbackCreate(
                vid_id="example1",
                label="Incorrect",
                comment="AI score is high when the video is clearly not AI.",
            ),
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(uuid.UUID(result["id"]))
        self.assertIsNotNone(added_record)
        self.assertEqual(added_record.vid_id, "example1")

    async def test_save_feedback_rejects_invalid_label(self) -> None:
        session = MagicMock()
        result = await save_feedback(
            session,
            FeedbackCreate(vid_id="example1", label="Maybe", comment=None),
        )
        self.assertEqual(result["status"], "storage_error")
        session.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
