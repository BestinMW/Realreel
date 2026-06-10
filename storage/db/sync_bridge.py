from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, Coroutine
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_ready = threading.Event()
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _loop_thread_main() -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop_ready.set()
    _loop.run_forever()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop_thread
    if _loop is not None:
        return _loop

    _loop_thread = threading.Thread(
        target=_loop_thread_main,
        name="db-sync-bridge",
        daemon=True,
    )
    _loop_thread.start()
    _loop_ready.wait()
    assert _loop is not None
    return _loop


async def _init_bridge() -> None:
    global _engine, _session_factory
    if _engine is not None and _session_factory is not None:
        return

    from storage.core.config import settings

    _engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        expire_on_commit=False,
        autoflush=False,
    )


async def bridge_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield one async database session for synchronous pipeline callers.

    Returns:
        AsyncGenerator[AsyncSession, None]: A single scoped SQLAlchemy session backed by the
        shared bridge engine. Yields nothing when ``DATABASE_URL`` cannot be initialized,
        causing callers such as ``persist_db_video_sync`` and ``run_repost_assessment_sync``
        to report skipped or failed persistence gracefully.
    """
    await _init_bridge()
    assert _session_factory is not None
    async with _session_factory() as session:
        yield session


def run_db_coroutine(coro: Coroutine[Any, Any, T]) -> T:
    """Run async database work on a dedicated background event loop.

    Args:
        coro (Coroutine[Any, Any, T]): Awaitable database operation to execute on the bridge
            loop (for example ``_persist_db_video_async`` or ``_save_feedback_async``).

    Returns:
        T: The coroutine result on success. Raises when the bridge cannot initialize or the
        coroutine fails; synchronous wrappers convert failures to
        ``{"ok": False, "videoId": None, "error": "<message>"}`` or
        ``{"status": "storage_error", "message": "unable to save to storage"}``.
    """
    loop = _ensure_loop()
    asyncio.run_coroutine_threadsafe(_init_bridge(), loop).result()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()
