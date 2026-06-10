# RealReel Backend

FastAPI service that downloads a video URL, runs the analysis pipeline, uploads artifacts to Supabase Storage, and returns a streaming NDJSON result to the frontend.

Supports YouTube, TikTok, Instagram, and direct video links where `yt-dlp` can fetch the file.

## Requirements

- Python 3.12+
- System binaries: `ffmpeg`, `yt-dlp`
- Optional: `tesseract-ocr` (keyframe on-screen text OCR)

Docker installs these automatically when using `backend/Dockerfile`.

### Windows (one-time)

From repo root:

```powershell
.\scripts\check-deps.ps1
```

Install missing tools:

```powershell
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp
winget install UB-Mannheim.TesseractOCR
```

Or use `.\scripts\start-backend.ps1`, which sets `TESSERACT_CMD` when Tesseract is in the default install path.

## Local setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env.local
uvicorn main:app --reload --port 8000
```

Shortcut from repo root: `.\scripts\start-backend.ps1`

Health check: http://localhost:8000/health

### Environment

`main.py` loads, in order:

1. `backend/.env`
2. `backend/.env.local` (overrides)
3. `storage/.env` (fallback, does not override existing vars)

Minimum secrets in `backend/.env.local`:

```env
OPENAI_API_KEY=...
GEMINI_API_KEY=...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
CORS_ORIGINS=http://localhost:3000
```

Optional Postgres (enables repost history + saving analyzed videos):

```env
DATABASE_URL=postgresql+asyncpg://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres
ENABLE_REPOST_ASSESSMENT=true
ENABLE_DATABASE_SAVE=true
```

If `DATABASE_URL` is unset, analysis still runs; repost check and DB save are skipped gracefully.

Storage buckets (`raw-videos`, `audio`, `transcripts`, `thumbnails`, `analysis`) are created automatically on first upload when Supabase credentials are set.

## API

### `GET /health`

Returns tool resolution (`ffmpeg`, `yt-dlp`, `tesseract`) and API version.

### `POST /process-youtube`

Request body (either field works):

```json
{ "videoUrl": "https://www.youtube.com/watch?v=..." }
```

Response: NDJSON stream (`application/x-ndjson`) with:

- `{"type":"progress","progress":42,"stage":"..."}`
- `{"type":"complete","progress":100,"result":{...}}`
- `{"type":"error","message":"..."}`

The `complete` result includes claim analysis, visual/temporal/thumbnail scores, repost fields (`isRepost`, `repostRisk`, `repostMatches`), storage paths, and `databaseSaveOk` / `databaseVideoId` when DB save ran.

## Pipeline overview

`pipeline/process.py` orchestrates the run:

| Stage | Module | Output |
|-------|--------|--------|
| Download | `download.py` | Local MP4 + yt-dlp metadata (`upload_date`, uploader, title) |
| Media prep | `media.py` | Audio WAV, sampled frames, keyframes, SHA-256 |
| Transcription | `transcribe.py` | `transcript.json` (OpenAI Whisper) |
| Temporal check | `temporal.py` | `temporal-consistency.json` |
| Visual events | `visual_events.py` | `visual-event-analysis.json` |
| Keyframes | `keyframes.py`, `ocr.py`, `vision.py` | `keyframe-analysis.json` |
| Repost check | `storage/services/reposts.py` | Hash match vs `videos` table (needs `DATABASE_URL`) |
| Metadata rules | `metadata_analyzer.py` | `metadata-analysis.json` |
| Thumbnail | `thumbnail.py` | Thumbnail image + clickbait analysis |
| Claim check | `claim_analysis.py` | `claim-analysis.json` (OpenAI + web search) |
| Upload | `pipeline/storage.py` | Supabase Storage artifacts |
| DB save | `storage/services/db_videos.py` | Upsert `public.videos` row |

### Fast processing mode

```env
FAST_PROCESSING_MODE=true
```

Skips visual event analysis, metadata analysis, thumbnail clickbait analysis, and raw MP4 upload. Does **not** skip transcription, keyframe vision, claim analysis, Supabase artifact uploads, repost check, or DB save.

### Claim analysis

```env
ENABLE_CLAIM_ANALYSIS=true
OPENAI_CLAIM_MODEL=gpt-4.1-mini
OPENAI_CLAIM_TIMEOUT_SECONDS=120
```

Uses OpenAI Responses API with web search. Set `ENABLE_CLAIM_ANALYSIS=false` to skip during testing.

### Vision provider

Default: Google AI Studio (`GEMINI_API_KEY`). For Vertex AI:

```env
VISION_PROVIDER=vertex_ai
VERTEX_AI_PROJECT_ID=your-project
VERTEX_AI_LOCATION=us-central1
VERTEX_AI_GEMINI_MODEL=gemini-2.5-flash
```

Authenticate with `gcloud auth application-default login` locally, or `GOOGLE_APPLICATION_CREDENTIALS` in deployment.

### Keyframe / visual event tuning

```env
KEYFRAME_SCENE_THRESHOLD=0.35
KEYFRAME_INTERVAL_SECONDS=5
MAX_KEYFRAMES_TO_ANALYZE=3
MAX_VISUAL_EVENT_FRAMES_TO_ANALYZE=6
VISUAL_EVENT_WINDOW_RADIUS_FRAMES=2
ENABLE_KEYFRAME_OCR=false
ENABLE_KEYFRAME_VISION=true
```

## Frontend connection

`frontend/.env.local`:

```env
PROCESSOR_URL=http://localhost:8000
```

The Next.js route `POST /api/process-youtube` proxies to `${PROCESSOR_URL}/process-youtube`.

## Tests

From repo root:

```bash
python scripts/run_tests.py
```

Backend tests live in `tests/backend/` (URL parsing, indicators, claim analysis, metadata rules, frame sampling, repost helpers).

## Layout

```text
backend/
  main.py                      FastAPI app, loads storage/.env fallback
  pipeline/
    process.py                 Main orchestration
    download.py                yt-dlp
    youtube.py                 URL parsing (YouTube, TikTok, Instagram, direct)
    media.py                   ffmpeg audio/frames/keyframes
    transcribe.py              OpenAI Whisper
    temporal.py                Frame-to-frame consistency
    visual_events.py           Suspicious temporal windows
    keyframes.py               Per-keyframe OCR + vision
    ocr.py / vision.py         Tesseract + Gemini
    claim_analysis.py          OpenAI fact-check
    metadata_analyzer.py       Container/metadata heuristics
    thumbnail.py               Thumbnail download + clickbait
    indicators.py              Shared normalization helpers
    storage.py                 Supabase Storage uploads
    config.py                  Env flags and bucket names
```

Unit tests for the backend live in `tests/backend/` at the repo root.
