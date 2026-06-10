"""Shared pytest configuration for RealReel unit tests."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"

for path in (PROJECT_ROOT, BACKEND_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")
os.environ.setdefault("EMBEDDING_DIMENSION", "512")

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(
        TimeoutException=TimeoutError,
        post=types.SimpleNamespace(),
    )


@pytest.fixture(scope="session", autouse=True)
def configure_test_environment() -> None:
    """Session hook reserved for future shared setup."""
