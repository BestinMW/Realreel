# RealReel Backend (Python)

Video processing API for Railway (or local dev). Supports YouTube, TikTok, Instagram, and direct video links where `yt-dlp` can download the media. Downloads video, extracts audio/frames, checks temporal frame consistency, transcribes with OpenAI, runs OCR + Gemini vision on keyframes, uploads to Supabase.
It also creates a claim analysis artifact that uses OpenAI web search to identify and fact-check the main factual claim in the video.

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

### Tesseract (on-screen text OCR)

If keyframe analysis shows `Tesseract OCR binary not found`, install Tesseract then **restart the backend**:

```powershell
winget install UB-Mannheim.TesseractOCR
```

Finish the installer UI if it opens. Default path:

`C:\Program Files\Tesseract-OCR\tesseract.exe`

Optional — add to `backend/.env.local`:

```env
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

To skip OCR entirely (vision still runs):

```env
ENABLE_KEYFRAME_OCR=false
```

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

Copy `backend/.env.example` to `backend/.env.local`, then fill in your real keys.

```env
OPENAI_API_KEY=your-openai-api-key
GEMINI_API_KEY=your-gemini-api-key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
```

### Claim analysis

After transcription and keyframe analysis, the backend writes `claim-analysis.json` and uploads it to the analysis bucket. It includes the detected claim, verdict, confidence, summary, evidence links, missing context, and recommended action.

Relevant settings:

```env
ENABLE_CLAIM_ANALYSIS=true
OPENAI_CLAIM_MODEL=gpt-4.1-mini
OPENAI_CLAIM_TIMEOUT_SECONDS=120
```

Set `ENABLE_CLAIM_ANALYSIS=false` to skip this stage while testing. This stage uses OpenAI Responses API web search, so it can add model-token cost plus web-search tool-call cost.

### Vertex AI Gemini vision

By default, keyframe vision uses the Google AI Studio Gemini API key. To use Gemini through Vertex AI and bill through a Google Cloud project instead:

```env
VISION_PROVIDER=vertex_ai
VERTEX_AI_PROJECT_ID=cs180-agentic-lab
VERTEX_AI_LOCATION=us-central1
VERTEX_AI_GEMINI_MODEL=gemini-2.5-flash
```

Then authenticate the backend with Google Cloud Application Default Credentials:

```powershell
gcloud auth application-default login
```

For deployment, set `GOOGLE_APPLICATION_CREDENTIALS` to a service account JSON file path. The project must have billing enabled, the Vertex AI API enabled, and the calling user/service account needs Vertex AI permissions.

### Temporal consistency

The backend writes `temporal-consistency.json` after extracting sampled frames. It compares adjacent sampled frames and reports:

- `temporalInstabilityScore`
- `aiVisualRiskScore`
- `objectDisappearanceRisk`
- frame-pair risk signals such as large visual changes without a detected scene cut

These are heuristic preprocessing signals, not a final fake/real verdict.

### Keyframe extraction

Keyframes are extracted with a hybrid strategy:

- the first frame
- detected scene changes above `KEYFRAME_SCENE_THRESHOLD`
- periodic frames at least `KEYFRAME_INTERVAL_SECONDS` apart

If more frames are extracted than `MAX_KEYFRAMES_TO_ANALYZE`, the analyzed set is spread across the whole video instead of taking only the earliest frames.

For destructive or suspicious videos, the backend also scans up to `MAX_VISUAL_EVENT_FRAMES_TO_ANALYZE` sampled frames selected from temporal-risk regions plus an even spread across the video. Around suspicious temporal changes, it analyzes a before/during/after frame window controlled by `VISUAL_EVENT_WINDOW_RADIUS_FRAMES`. These results are saved as `visual-event-analysis.json` and fed into claim analysis so obvious synthetic explosion/fire/smoke cues can force a review instead of being treated as real footage.

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
{ "videoUrl": "https://www.youtube.com/watch?v=..." }
```

Response: NDJSON stream (`application/x-ndjson`) with `progress`, `complete`, and `error` events (same shape as the former Next.js route).

The backend still accepts the older `{ "youtubeUrl": "..." }` field for compatibility. TikTok and public Instagram reels/posts/stories are passed to `yt-dlp`; private, age-gated, or login-required Instagram links may fail unless cookie support is added later.

## Layout

```text
backend/
  main.py                 # FastAPI app
  pipeline/
    process.py            # orchestration
    download.py           # yt-dlp
    media.py              # ffmpeg
    transcribe.py         # OpenAI Whisper API
    temporal.py           # sampled-frame temporal consistency
    ocr.py                # pytesseract + indicators
    vision.py             # Gemini
    keyframes.py          # per-frame analysis
    claim_analysis.py     # OpenAI web-search fact checking
    indicators.py         # shared heuristics / schema
    storage.py            # Supabase uploads
```
