from __future__ import annotations

import asyncio
import socket
import sys
import time
from decimal import Decimal
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from storage.core.config import settings
    from storage.db.models import Platform
    from storage.db.session import AsyncSessionLocal
    from storage.schemas import VideoCreate
    from storage.services import (
        find_video_by_sha256,
        find_video_by_url,
        save_analyzed_video,
    )
    from storage.vector import find_similar_videos
except Exception as exc:
    print("Could not load storage settings.")
    print("Make sure your environment variables are set from storage/env.example.")
    print("Also make sure you already ran storage/schema.sql in Supabase.")
    print(f"Details: {type(exc).__name__}: {exc}")
    raise SystemExit(1) from exc


def make_embedding(seed: float = 0.01) -> list[float]:
    return [seed] * settings.embedding_dimension


async def main() -> None:
    unique_value = str(int(time.time()))
    original_url = f"https://example.com/realreel-smoke-test-{unique_value}.mp4"
    file_sha256 = f"{unique_value:0>64}"[-64:]

    payload = VideoCreate(
        original_url=original_url,
        platform=Platform.DIRECT_UPLOAD,
        title="RealReel smoke test video",
        raw_video_path=f"videos/smoke-test-{unique_value}/raw/original.mp4",
        thumbnail_path=f"videos/smoke-test-{unique_value}/thumbnails/thumbnail.jpg",
        transcript_text="Smoke test transcript.",
        duration_seconds=Decimal("10.0"),
        file_sha256=file_sha256,
        video_embedding=make_embedding(),
        embedding_model="smoke-test-model",
        ai_generated_score=Decimal("0.1000"),
        misleading_context_score=Decimal("0.2000"),
        repost_probability=Decimal("0.3000"),
        credibility_score=Decimal("0.9000"),
        overall_risk_score=Decimal("0.2500"),
        confidence=Decimal("0.9500"),
        reasons={"summary": "Smoke test row created by storage/smoke_test.py"},
    )

    async with AsyncSessionLocal() as session:
        video = await save_analyzed_video(session, payload)
        await session.commit()
        print(f"Created video row: {video.id}")

        by_url = await find_video_by_url(session, original_url)
        if by_url is None:
            raise RuntimeError("Could not retrieve video by original_url.")
        print("Retrieved video by URL.")

        by_hash = await find_video_by_sha256(session, file_sha256)
        if by_hash is None:
            raise RuntimeError("Could not retrieve video by file_sha256.")
        print("Retrieved video by file_sha256.")

        matches = await find_similar_videos(
            session,
            embedding=make_embedding(),
            limit=5,
            max_cosine_distance=0.01,
        )
        if not any(str(match["id"]) == str(video.id) for match in matches):
            raise RuntimeError("Similarity search did not return the smoke test row.")
        print(f"Similarity search returned {len(matches)} match(es).")

        await session.delete(video)
        await session.commit()
        print("Deleted smoke test row.")

    print("Storage/database smoke test passed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except socket.gaierror as exc:
        print("Could not resolve the database host in DATABASE_URL.")
        print("Check that DATABASE_URL does not still contain a placeholder like db.your-project.supabase.co.")
        print("Copy the connection string from Supabase's Connect button, then replace [YOUR-PASSWORD].")
        raise SystemExit(1) from exc
    except Exception as exc:
        print(f"Storage/database smoke test failed: {type(exc).__name__}: {exc}")
        raise
