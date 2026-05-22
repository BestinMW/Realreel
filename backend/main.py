import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pipeline.config import CORS_ORIGINS
from pipeline.process import process_youtube_video

_backend_dir = Path(__file__).resolve().parent
load_dotenv(_backend_dir / ".env")
load_dotenv(_backend_dir / ".env.local", override=True)

app = FastAPI(title="RealReel Processor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProcessRequest(BaseModel):
    youtubeUrl: str


@app.get("/health")
def health() -> dict:
    """Check API and resolved tool paths (restart backend after code changes)."""
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
async def process_youtube(request: ProcessRequest) -> StreamingResponse:
    async def event_stream() -> AsyncGenerator[bytes, None]:
        for event in process_youtube_video(request.youtubeUrl):
            yield (json.dumps(event) + "\n").encode("utf-8")

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-transform"},
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
