import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")

from pipeline.media import compute_file_sha256  # noqa: E402
from storage.services.reposts import (  # noqa: E402
    extract_repost_match_date,
    repost_risk_score,
)


class RepostIntegrationTests(unittest.TestCase):
    def test_compute_file_sha256_is_stable(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"realreel-repost-test")
            temp_path = Path(handle.name)

        try:
            self.assertEqual(
                compute_file_sha256(temp_path),
                compute_file_sha256(temp_path),
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def test_extract_repost_match_date_from_platform_upload_date(self) -> None:
        assessment = {
            "matches": [{"platformUploadDate": "2023-01-15"}],
        }
        self.assertEqual(extract_repost_match_date(assessment), "20230115")

    def test_repost_risk_score_floors_confirmed_reposts(self) -> None:
        self.assertEqual(
            repost_risk_score(
                {
                    "isRepost": True,
                    "repostProbability": Decimal("0.8200"),
                }
            ),
            0.82,
        )
        self.assertEqual(
            repost_risk_score(
                {
                    "isRepost": True,
                    "repostProbability": Decimal("0.4000"),
                }
            ),
            0.65,
        )

    def test_repost_risk_score_ignores_clean_no_match_results(self) -> None:
        self.assertIsNone(
            repost_risk_score(
                {
                    "isRepost": False,
                    "repostProbability": Decimal("0.0000"),
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
