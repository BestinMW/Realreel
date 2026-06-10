from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from storage.assets.paths import StorageBucket
from storage.assets.supabase import storage_service
from storage.db.session import get_db_session
from storage.schemas import (
    AssetSignedUrlRequest,
    FeedbackCreate,
    FeedbackRead,
    FeedbackSaveResult,
    SignedUrlResponse,
    SimilarVideoQuery,
    SimilarVideoRead,
    VideoCreate,
    VideoRead,
)
from storage.services.feedback import save_feedback
from storage.services import (
    delete_video_and_assets,
    find_video_by_sha256,
    find_video_by_url,
    get_video_or_raise,
    list_recent_videos,
    save_analyzed_video,
)
from storage.vector import find_similar_videos


router = APIRouter(prefix="/storage", tags=["storage"])


@router.post("/videos", response_model=VideoRead, status_code=status.HTTP_201_CREATED)
async def save_video_result(
    payload: VideoCreate,
    session: AsyncSession = Depends(get_db_session),
) -> VideoRead:
    """Persist a completed analysis via ``POST /storage/videos`` (engine -> storage).

    Args:
        payload (VideoCreate): Completed analysis row with ``original_url``, ``file_sha256``,
            risk scores, and ``reasons``.
        session (AsyncSession): Injected async database session.

    Returns:
        VideoRead: HTTP 201 response with the saved video row (includes ``id``, scores,
        and paths). On persistence failure, raises HTTP 500 (equivalent to
        ``{"status": "storage_error", "message": "unable to save to storage"}`` for
        feedback; video save errors surface as HTTP exceptions).
    """
    video = await save_analyzed_video(session, payload)
    await session.commit()
    return VideoRead.model_validate(video)


@router.get("/videos", response_model=list[VideoRead])
async def get_recent_videos(
    limit: int = Query(default=25, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[VideoRead]:
    videos = await list_recent_videos(session, limit)
    return [VideoRead.model_validate(video) for video in videos]


@router.get("/videos/by-url", response_model=VideoRead | None)
async def get_video_by_url(
    original_url: str,
    session: AsyncSession = Depends(get_db_session),
) -> VideoRead | None:
    video = await find_video_by_url(session, original_url)
    return VideoRead.model_validate(video) if video else None


@router.get("/videos/by-sha256", response_model=VideoRead | None)
async def get_video_by_sha256(
    file_sha256: str,
    session: AsyncSession = Depends(get_db_session),
) -> VideoRead | None:
    video = await find_video_by_sha256(session, file_sha256)
    return VideoRead.model_validate(video) if video else None


@router.post("/videos/similar", response_model=list[SimilarVideoRead])
async def get_similar_videos(
    payload: SimilarVideoQuery,
    session: AsyncSession = Depends(get_db_session),
) -> list[SimilarVideoRead]:
    matches = await find_similar_videos(
        session,
        embedding=payload.embedding,
        limit=payload.limit,
        max_cosine_distance=payload.max_cosine_distance,
        exclude_video_id=payload.exclude_video_id,
    )
    return [SimilarVideoRead.model_validate(match) for match in matches]


@router.get("/videos/{video_id}", response_model=VideoRead)
async def get_video(
    video_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> VideoRead:
    try:
        video = await get_video_or_raise(session, video_id)
        return VideoRead.model_validate(video)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/assets/signed-url", response_model=SignedUrlResponse)
async def create_asset_signed_url(payload: AssetSignedUrlRequest) -> SignedUrlResponse:
    try:
        bucket = StorageBucket(payload.bucket)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown storage bucket.") from exc

    expires_in = payload.expires_in
    signed_url = await storage_service.create_signed_url(
        bucket=bucket,
        storage_path=payload.storage_path,
        expires_in=expires_in,
    )
    return SignedUrlResponse(
        signed_url=signed_url,
        expires_in=expires_in or 900,
    )


@router.delete("/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(
    video_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    try:
        await delete_video_and_assets(session, video_id=video_id)
        await session.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/feedback", response_model=FeedbackSaveResult)
async def create_feedback(
    payload: FeedbackCreate,
    session: AsyncSession = Depends(get_db_session),
) -> FeedbackSaveResult:
    """Persist analysis feedback via ``POST /storage/feedback`` (engine -> storage).

    Args:
        payload (FeedbackCreate): Feedback with ``vid_id``, ``label`` (``Correct`` or
            ``Incorrect``), and optional ``comment``.
        session (AsyncSession): Injected async database session.

    Returns:
        FeedbackSaveResult: HTTP 200 with ``{"status": "success", "id": "<feedback-uuid>"}``.
        HTTP 500 when ``save_feedback`` returns
        ``{"status": "storage_error", "message": "unable to save to storage"}``.
    """
    result = await save_feedback(session, payload)
    if result["status"] == "success":
        await session.commit()
        return FeedbackSaveResult(status="success", id=result["id"])
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=result.get("message", "unable to save to storage"),
    )


def create_app() -> FastAPI:
    app = FastAPI(title="RealReel Storage API")
    app.include_router(router)
    return app
