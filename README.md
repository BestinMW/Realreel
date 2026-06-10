# RealReel

RealReel helps you judge whether a social video is trustworthy. Paste a link from YouTube, TikTok, Instagram, Vimeo, or a direct video URL, and the app downloads the clip, analyzes misleading context and AI-generated visuals, checks repost history when configured, and shows a reliability score with a plain-language explanation. You can also submit feedback when an analysis looks right or wrong.

## Repository information

| Item | Path or link |
|------|----------------|
| **Source code** | [`frontend/`](frontend/) (interface), [`backend/`](backend/) (engine), [`storage/`](storage/) (persistence) |
| **Tests** | [`tests/`](tests/) (`tests/interface/`, `tests/engine/`, `tests/storage/`) |
| **Requirements specification and design** | [`docs/REQUIREMENTS_AND_DESIGN.md`](docs/REQUIREMENTS_AND_DESIGN.md) |
| **Demo video** | [`docs/demo.mp4`](docs/demo.mp4) |
| **Report** | [`docs/REPORT.md`](docs/REPORT.md) |

## Setup

### Dependencies

Install these before your first run:

| Dependency | Purpose |
|------------|---------|
| **Python 3.12+** | Backend processor and storage services |
| **Node.js** | Next.js web UI |
| **ffmpeg** | Audio extraction and frame sampling |
| **yt-dlp** | Video download from supported platforms |
| **Tesseract OCR** (optional) | On-screen text in keyframes |

On Windows, from the repo root:

```powershell
.\scripts\check-deps.ps1
```

Missing tools can be installed with `winget` (see `backend/README.md`).

### Python and Node packages

The start scripts install these automatically on first run. To install manually:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r ..\requirements.txt

cd ..\frontend
npm install
```

### One-time configuration

1. **Supabase (recommended)**  
   - Create a Supabase project.  
   - Run `storage/schema.sql` once in the Supabase SQL Editor (creates `videos`, `analysis_feedback`, and storage buckets).  
   - Copy your project URL, service role key, and Postgres connection string from the dashboard.

2. **Backend credentials** — create `backend/.env.local`:

```env
OPENAI_API_KEY=your-openai-api-key
GEMINI_API_KEY=your-gemini-api-key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
CORS_ORIGINS=http://localhost:3000
```

3. **Database (optional, enables repost checks and saving results)** — add to `backend/.env.local`:

```env
DATABASE_URL=postgresql+asyncpg://postgres.[ref]:[password]@....pooler.supabase.com:5432/postgres
ENABLE_REPOST_ASSESSMENT=true
ENABLE_DATABASE_SAVE=true
```

You can mirror the same Supabase/Postgres values in `storage/.env`; the backend loads that file as a fallback.

4. **Frontend** — create `frontend/.env.local`:

```env
PROCESSOR_URL=http://localhost:8000
```

Analysis still runs without `DATABASE_URL`; repost history, database saves, and feedback persistence require Postgres to be configured and the schema applied.

## Execution instructions

Use two terminals from the repository root.

**Terminal 1 — backend**

```powershell
.\scripts\start-backend.ps1
```

Verify: http://localhost:8000/health

**Terminal 2 — frontend**

```powershell
.\scripts\start-frontend.ps1
```

Open the app: http://localhost:3000

Paste a video URL, optionally turn on **Fast mode**, then click **Process Video**.

## Usage examples

### Example 1: Preview and submit a YouTube link

**Input**

- URL: `https://www.youtube.com/watch?v=dQw4w9WgXcQ`
- Fast mode: Off

**What you see**

- An embedded YouTube preview in the page.
- **Process Video** enabled after the URL validates.
- A progress bar with stages such as `Downloading`, `Transcribing`, `Analyzing claim`.
- When finished, a **Reliability Score** (0–100%) and a short explanation built from claim, visual, thumbnail, and repost signals.

**If something goes wrong**

- Empty or invalid URL → prompt to enter a full `https://` link; button stays disabled.
- Backend not running → error that the processor could not be reached.

### Example 2: Reliability analysis and repost signals

**Input**

- URL: `https://www.tiktok.com/@example/video/1234567890`
- Fast mode: Off (full analysis including metadata and thumbnail checks)

**Expected output (illustrative)**

| Field | Example value | Meaning |
|-------|---------------|---------|
| `misleadingProbability` | `0.65` | Risk the video could mislead viewers (0–1) |
| `visualAuthenticityRisk` | `0.72` | Risk the footage is AI-generated or synthetic (0–1) |
| Reliability score (UI) | `28%` | `100 × (1 − max(risk scores))` |
| `claimSummary` | Short text | What the video appears to claim |
| `isRepost` / `repostRationale` | When DB is configured | Whether similar footage was uploaded earlier |

If there is no clear spoken claim, the backend may return `claimVerdict: no_clear_claim` and still show visual and repost rationales. With Supabase configured, artifacts and scores can be saved for later repost comparison.

### Example 3: Analysis feedback

**Input** (after a completed analysis)

- Label: **Incorrect**
- Comment: `AI score is high when the video is clearly not AI.`

**Expected output**

- Message: `feedback submitted`
- Record stored in `public.analysis_feedback` when the database is configured.

**If something goes wrong**

- Missing label → `empty feedback`
- Database unavailable → `feedback to storage failure`

## Project structure

RealReel uses three layers — interface, engine, and storage — rather than a single `src/` folder.

| Path | Layer | Role |
|------|-------|------|
| `frontend/` | Interface | Next.js UI, URL preview, progress display, reliability score, feedback form |
| `frontend/app/api/` | Interface | Proxies to the backend (`process-youtube`, `feedback`) |
| `backend/` | Engine | FastAPI app, video download, analysis pipeline |
| `backend/pipeline/` | Engine | Transcription, vision, claim check, metadata, thumbnail, orchestration |
| `storage/` | Storage | Postgres models, repost detection, feedback persistence, path templates |
| `storage/schema.sql` | Storage | Database and bucket setup for Supabase |
| `requirements.txt` | — | Single Python dependency file (backend, storage, tests) |
| `scripts/` | — | `start-backend.ps1`, `start-frontend.ps1`, `check-deps.ps1`, `run_tests.py` |
| `docs/` | — | Requirements and design reference |

### Tests

| Path | Layer | What it covers |
|------|-------|----------------|
| `tests/interface/` | Interface | Reliability score display logic |
| `tests/engine/` | Engine | URL parsing, indicators, claim analysis, metadata rules, feedback validation |
| `tests/storage/` | Storage | Video payloads, repost rules, feedback persistence |
| `tests/conftest.py` | — | Shared test environment setup |

Run tests:

```powershell
pip install -r requirements.txt
python scripts/run_tests.py

OR

pip install -r requirements.txt
python -m pytest --cov=backend --cov=storage --cov-report=term-missing tests/
```
