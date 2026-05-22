# RealReel Backend (Python)

YouTube processing API for Railway (or local dev). Downloads video, extracts audio/frames, transcribes with OpenAI, runs OCR + Gemini vision on keyframes, uploads to Supabase.

The Next.js app on Vercel proxies `/api/process-youtube` to this service.

## Requirements

- Python 3.12+
- System binaries: `ffmpeg`, `yt-dlp`, `tesseract-ocr`

Docker installs these automatically (see `Dockerfile`).

### Windows (one-time)

From repo root, check tools:

```powershell
.\scripts\check-deps.ps1
```

If anything is missing:

```powershell
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp
winget install UB-Mannheim.TesseractOCR
```

Restart the terminal after installing.

## Local setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
# Put secrets in backend/.env.local (python-dotenv loads it automatically)
uvicorn main:app --reload --port 8000
```

Health check: http://localhost:8000/health

## Frontend connection

In `frontend/.env.local`:

```env
PROCESSOR_URL=http://localhost:8000
```

`npm run dev` proxies `POST /api/process-youtube` to `${PROCESSOR_URL}/process-youtube`.

On Railway, set `PROCESSOR_URL` in Vercel to your Railway public URL.

## Railway deploy

1. New service from repo, root directory `backend`
2. Use Dockerfile or Nixpacks with `ffmpeg`, `tesseract-ocr`, `yt-dlp` available
3. Set env vars from `.env.example`
4. Set `CORS_ORIGINS` to your Vercel URL(s)
5. Copy `PROCESSOR_URL` into Vercel env

Start command (if not using Dockerfile):

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## API

`POST /process-youtube`

Body:

```json
{ "youtubeUrl": "https://www.youtube.com/watch?v=..." }
```

Response: NDJSON stream (`application/x-ndjson`) with `progress`, `complete`, and `error` events (same shape as the former Next.js route).

## Layout

```text
backend/
  main.py                 # FastAPI app
  pipeline/
    process.py            # orchestration
    download.py           # yt-dlp
    media.py              # ffmpeg
    transcribe.py         # OpenAI Whisper API
    ocr.py                # pytesseract + indicators
    vision.py             # Gemini
    keyframes.py          # per-frame analysis
    indicators.py         # shared heuristics / schema
    storage.py            # Supabase uploads
```
