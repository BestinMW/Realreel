# RealReel Storage and Database

Postgres schema, Supabase Storage path conventions, and Python services for persisting **completed** video analyses. The backend analysis pipeline imports this package through `backend/adapters/`; no separate storage server is required.

In-progress jobs are not tracked here—only finished runs upsert into `public.videos`.

## What gets stored

Each analyzed video can produce:

1. **Files** in private Supabase Storage buckets (paths stored on the row; uploaded by `backend/adapters/object_storage.py`)
2. **One Postgres row** in `videos` with scores, metadata, and JSON `reasons`

The backend saves the row after uploads when `DATABASE_URL` is set (`ENABLE_DATABASE_SAVE=true` by default).

## `videos` table

Key columns:

| Column | Meaning |
|--------|---------|
| `original_url` | Submitted URL (unique) |
| `platform` | `youtube`, `tiktok`, `instagram`, etc. |
| `uploader_handle`, `uploader_url` | Channel / author from yt-dlp |
| `platform_upload_date` | Platform publish date (`date`, from yt-dlp `upload_date`) |
| `file_sha256` | Exact file hash (unique) |
| `raw_video_path`, `thumbnail_path`, `transcript_path` | Supabase Storage object paths |
| `transcript_text` | Truncated transcript excerpt |
| `video_embedding` | Optional whole-video vector (512-dim pgvector) |
| `ai_generated_score` | Visual authenticity risk (0–1) |
| `misleading_context_score` | Misleading probability (0–1) |
| `repost_probability` | Repost risk (0–1) |
| `overall_risk_score` | `max(misleading, visual, thumbnail, repost)` at save time |
| `credibility_score` | `1 − overall_risk_score` |
| `confidence` | Claim-analysis confidence |
| `reasons` | JSONB detail (claim summary, analysis paths, repost assessment, etc.) |
| `created_at`, `updated_at` | When RealReel saved/updated the row (not platform publish date) |

Run `schema.sql` once in Supabase **SQL Editor**. If you already created the table earlier, run the migration comments at the bottom of `schema.sql` to add `platform_upload_date`.

## Repost detection

`storage/services/reposts.py` compares a new video against saved rows:

1. **Exact hash** — same `file_sha256`, different URL
2. **Embedding similarity** — when `video_embedding` exists on saved rows

A match is flagged as a repost only when:

- It is a different post (not the same URL; different author or publish date)
- The current video's `platform_upload_date` is **later** than the matched row's

Re-analyzing the same URL does not count as a repost. Rows without `platform_upload_date` cannot satisfy the date rule until re-analyzed (date comes from yt-dlp at pipeline time).

The backend calls repost assessment during the pipeline; results appear in the stream result and in `reasons.repost` on save.

## File layout

```text
storage/
  schema.sql                 Supabase SQL (table, indexes, buckets)
  core/config.py             Pydantic settings from env
  db/
    models.py                SQLAlchemy `Video` model
    session.py               Async engine for integration tests
    sync_bridge.py           Background event loop for sync pipeline DB calls
  services/
    videos.py                Upsert analyzed rows (`persist_analyzed_video`)
    db_videos.py             Map pipeline result → `VideoCreate` → upsert
    reposts.py               Repost rules and sync bridge entrypoint
    feedback.py              Persist analysis feedback
  vector/search.py           pgvector cosine similarity
  assets/paths.py            Supabase object path templates
  schemas/contracts.py       Pydantic `VideoCreate`, `FeedbackCreate`
  requirements.txt           Redirects to repo-root requirements.txt
```

Storage tests live in `tests/storage/` at the repo root (`test_pipeline_units.py`, `test_storage_reposts.py`, `test_db_videos.py`, `test_feedback.py`, `smoke_test.py`).

## Supabase setup

1. Create a Supabase project.
2. Paste and run `storage/schema.sql` in SQL Editor.
3. Copy connection string and keys into `storage/.env` (and/or `backend/.env.local`).

```env
DATABASE_URL=postgresql+asyncpg://postgres.[ref]:[password]@....pooler.supabase.com:5432/postgres
EMBEDDING_DIMENSION=512
```

Supabase Storage credentials and bucket names belong in `backend/.env.local` (see root `README.md`). Only the backend should use `SUPABASE_SERVICE_ROLE_KEY`.

Install Python deps (for tests or smoke test):

```bash
pip install -r requirements.txt
```

(`storage/requirements.txt` redirects to the repo-root file.)

## Storage buckets

Private buckets (created by `schema.sql` or auto-created by the backend on first upload):

| Bucket | Typical content |
|--------|-----------------|
| `raw-videos` | Source MP4 (optional; skipped unless `UPLOAD_RAW_VIDEO=true`) |
| `audio` | Extracted WAV |
| `transcripts` | Transcript JSON |
| `thumbnails` | Preview JPEG |
| `analysis` | Claim, temporal, metadata, repost JSON artifacts |

Object paths follow `storage/assets/paths.py` templates. Files are uploaded by `backend/adapters/object_storage.py` (httpx), not by a Python Supabase client in this package.

## How the backend uses this package

`backend/main.py` adds the repo root to `sys.path` and loads `storage/.env` as a fallback.

During `process_youtube_video`, `backend/adapters/` calls:

- **Repost** — `run_repost_assessment_sync()` via `sync_bridge` (needs `DATABASE_URL`)
- **Save** — `persist_db_video_sync()` builds a `VideoCreate` payload including `platform_upload_date` from yt-dlp metadata
- **Feedback** — `save_feedback_sync()` when the user submits Correct/Incorrect feedback
- **Uploads** — `upload_to_supabase_storage()` in `backend/adapters/object_storage.py` (not in `storage/`)

No separate storage server is required for the default app.

## Testing

Unit tests (no live database):

```bash
python scripts/run_tests.py
```

Storage-specific tests only:

```bash
python -m pytest tests/storage/ -v
```

Live integration (creates and deletes one test row; requires valid `DATABASE_URL`):

```bash
python tests/storage/smoke_test.py
```

## pgvector

`videos.video_embedding` uses `vector(512)` with an HNSW index. Similarity search lives in `vector/search.py` and powers embedding-based repost candidates when embeddings are populated.

## Inspecting data in Supabase

**Table Editor** → `public.videos`, or SQL:

```sql
select
  original_url,
  uploader_handle,
  platform_upload_date,
  overall_risk_score,
  created_at
from public.videos
order by created_at desc
limit 20;
```

`created_at` is when RealReel saved the analysis. Use `platform_upload_date` for when the video was posted on the platform.
