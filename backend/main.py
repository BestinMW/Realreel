import json
import os
import asyncio
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

_backend_dir = Path(__file__).resolve().parent
_repo_root = _backend_dir.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
load_dotenv(_backend_dir / ".env")
load_dotenv(_backend_dir / ".env.local", override=True)
load_dotenv(_repo_root / "storage" / ".env", override=False)

from pipeline.config import CORS_ORIGINS
from pipeline.process import process_youtube_video

app = FastAPI(title="RealReel Processor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProcessRequest(BaseModel):
    youtubeUrl: str | None = None
    videoUrl: str | None = None
    fastProcessingMode: bool | None = None


class FeedbackRequest(BaseModel):
    vid_id: str = ""
    label: str = ""
    comment: str = ""


@app.get("/health")
def health() -> dict:
    """Check API availability and resolved external tool paths.

    Args:
        None

    Returns:
        dict: ``{"ok": true, "version": "<date>", "tools": {"ffmpeg": "<path>", "yt_dlp": "<command>", "tesseract": "<path>|"missing: ..."}}``.
        Tool entries are ``None``-free strings; missing tools use a ``"missing: ..."`` message.
    """
    from pipeline.tools import get_ffmpeg_command, get_ytdlp_command, resolve_tesseract_path

    tools: dict[str, str | None] = {}
    for name, resolver in (
        ("ffmpeg", lambda: get_ffmpeg_command()[0]),
        ("yt_dlp", lambda: " ".join(get_ytdlp_command())),
        ("tesseract", resolve_tesseract_path),
    ):
        try:
            tools[name] = resolver()
        except FileNotFoundError as exc:
            tools[name] = f"missing: {exc}"

    return {"ok": True, "version": "2026-05-22", "tools": tools}


@app.post("/process-youtube")
async def process_youtube(payload: ProcessRequest, request: Request) -> StreamingResponse:
    """Stream video download, analysis, and persistence progress as NDJSON.

    Args:
        payload (ProcessRequest): Request body with ``videoUrl`` or ``youtubeUrl`` and
            optional ``fastProcessingMode`` boolean.
        request (Request): FastAPI request used to detect client disconnect.

    Returns:
        StreamingResponse: NDJSON stream of events. Progress events use
        ``{"type": "progress", "progress": <int>, "stage": "<label>"}``. The final
        success event uses
        ``{"type": "complete", "progress": 100, "stage": "Complete", "result": {...}}``
        where ``result`` includes analysis scores, rationales, repost fields, storage
        paths, and ``databaseSaveOk`` / ``databaseVideoId`` when configured. Failure
        events use ``{"type": "error", "message": "<user-readable reason>"}`` (e.g.
        download failure, invalid URL). Streaming stops if the client disconnects.
    """
    async def event_stream() -> AsyncGenerator[bytes, None]:
        """Yield NDJSON-encoded pipeline events until completion or client disconnect.

        Args:
            None

        Returns:
            AsyncGenerator[bytes, None]: UTF-8 encoded lines from ``process_youtube_video``;
            iteration stops when the generator exhausts or the client disconnects.
        """
        url = payload.videoUrl or payload.youtubeUrl or ""
        for event in process_youtube_video(
            url,
            fast_processing_mode=payload.fastProcessingMode,
        ):
            if await request.is_disconnected():
                break
            yield (json.dumps(event) + "\n").encode("utf-8")
            await asyncio.sleep(0)

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-transform"},
    )


@app.post("/feedback")
def submit_analysis_feedback(payload: FeedbackRequest) -> JSONResponse:
    """HTTP entry point for analysis feedback (interface -> engine contract).

    Args:
        payload (FeedbackRequest): JSON body with ``vid_id``, ``label`` (``Correct`` or
            ``Incorrect``), and optional ``comment``.

    Returns:
        JSONResponse: HTTP 200 with ``{"status": "success", "message": "feedback submitted"}``.
        HTTP 400 with ``{"status": "missing_fields", "message": "empty feedback"}``.
        HTTP 500 with ``{"status": "storage_error", "message": "feedback to storage failure"}``.
    """
    from adapters.feedback import submit_feedback

    result = submit_feedback(
        vid_id=payload.vid_id,
        label=payload.label,
        comment=payload.comment,
    )
    status_code = 200
    if result["status"] == "missing_fields":
        status_code = 400
    elif result["status"] == "storage_error":
        status_code = 500
    return JSONResponse(content=result, status_code=status_code)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
