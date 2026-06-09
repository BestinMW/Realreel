# RealReel

RealReel analyzes short-form and social videos for misleading context, visual authenticity risk, thumbnail clickbait, and repost history. Users paste a URL in the web UI; a Python backend downloads the video, runs the analysis pipeline, uploads artifacts to Supabase Storage, and optionally saves scores to Postgres.

## Repository layout

```text
Realreel/
  frontend/          Next.js UI
  backend/           FastAPI video processor
  storage/           Postgres + Supabase Storage layer (used by the backend)
  scripts/           start-backend.ps1, start-frontend.ps1, run_tests.py, check-deps.ps1
```

| Package | Role |
|---------|------|
| **frontend** | Preview URLs, stream analysis progress, show reliability score and rationales |
| **backend** | Download (yt-dlp), ffmpeg media prep, transcription, vision/OCR, claim check, uploads |
| **storage** | `videos` table schema, repost lookup, pgvector search, optional REST API module |

The backend imports `storage/` at runtime (repo root is added to `sys.path` in `backend/main.py`). The default processor app does **not** mount the storage FastAPI router; the analysis pipeline calls storage services directly for repost checks and DB saves.

## How a run works

1. Frontend `POST /api/process-youtube` proxies to backend `POST /process-youtube`.
2. Backend streams NDJSON progress events, then a `complete` result with scores and paths.
3. Artifacts (audio, transcript, analysis JSON, thumbnail) upload to **Supabase Storage** buckets.
4. If `DATABASE_URL` is set, the backend also:
   - checks repost history against saved videos (hash match today; embedding similarity when available)
   - upserts one row in `public.videos` with scores and `platform_upload_date`

## Quick start (local)

**Prerequisites:** Python 3.12+, Node.js, `ffmpeg`, `yt-dlp`. Tesseract is optional (OCR).

```powershell
# From Realreel/
.\scripts\check-deps.ps1
.\scripts\start-backend.ps1    # terminal 1 — http://localhost:8000/health
.\scripts\start-frontend.ps1   # terminal 2 — http://localhost:3000
```

### Environment files

| File | Purpose |
|------|---------|
| `backend/.env.local` | API keys, Supabase, optional `DATABASE_URL`, pipeline flags |
| `storage/.env` | Same Supabase/Postgres vars (backend loads this as a fallback) |
| `frontend/.env.local` | `PROCESSOR_URL=http://localhost:8000` only |

## Tests

Unit tests:

```bash
python scripts/run_tests.py
```

This discovers `backend/tests` and `storage/tests`. Storage integration smoke test (requires real `DATABASE_URL`):

```bash
python storage/tests/smoke_test.py
```

## Reliability score (UI)

The frontend computes:

```text
reliability = 100 × (1 − max(misleadingProbability, visualAuthenticityRisk, thumbnailClickbaitScore, repostRisk))
```

Each risk is on a 0–1 scale from the backend result. Repost is a separate score, not folded into misleading probability.

## More documentation

- [backend/README.md](backend/README.md) — pipeline stages, env vars, API
- [storage/README.md](storage/README.md) — `videos` table, buckets, repost logic, optional REST API
- [frontend/README.md](frontend/README.md) — UI proxy and local setup
