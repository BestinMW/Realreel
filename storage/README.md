# RealReel Storage and Database Layer

This folder stores completed video analysis results and the file paths for
assets saved in Supabase Storage. It does not track in-progress processing.

## Simple Design

RealReel currently uses one main database table:

```text
videos
```

Each row represents one fully analyzed video. The row stores:

- the original submitted URL
- basic platform/uploader metadata
- Supabase Storage paths for the raw video, thumbnail, and transcript artifact
- transcript text if available
- one whole-video embedding for similarity search
- final analysis scores
- JSON reasons/explanations
- timestamps

Frame-by-frame embeddings, processing jobs, and separate analysis tables were
removed because the database is only being used to retrieve previously analyzed
videos.

## Files

```text
storage/
  api/
    routes.py          FastAPI routes for saving/finding analyzed videos
  assets/
    paths.py           Supabase Storage bucket names and object paths
    supabase.py        Upload, signed URL, and delete helpers
  core/
    config.py          Environment variable settings
  db/
    models.py          SQLAlchemy database model for the videos table
    session.py         Async SQLAlchemy database connection/session
  schemas/
    contracts.py       Pydantic request/response shapes
  services/
    videos.py          Database service helpers
  vector/
    search.py          Whole-video pgvector similarity search
  schema.sql           SQL to paste into Supabase SQL Editor
  requirements.txt     Python dependencies
  env.example          Required environment variables
```

## Supabase Setup

Install Python dependencies:

```bash
pip install -r storage/requirements.txt
```

Then open Supabase Dashboard > SQL Editor, paste `storage/schema.sql`, and run
it once.

That script creates:

- `pgvector`
- `pgcrypto`
- `video_platform` enum
- `videos` table
- indexes for lookup and vector search
- private Supabase Storage buckets

## Environment Variables

Use `storage/env.example` as the template:

```text
DATABASE_URL=postgresql+asyncpg://...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
EMBEDDING_DIMENSION=512
SIGNED_URL_TTL_SECONDS=900
RAW_VIDEOS_BUCKET=raw-videos
TRANSCRIPTS_BUCKET=transcripts
THUMBNAILS_BUCKET=thumbnails
```

Only the backend should use `SUPABASE_SERVICE_ROLE_KEY`. Never expose it in the
frontend.

## Storage Buckets

The simplified setup uses three private buckets:

- `raw-videos`: downloaded source video files
- `transcripts`: JSON/text transcript artifacts
- `thumbnails`: preview images

The database stores only the path, not the actual file.

Example:

```text
bucket: raw-videos
path: videos/{video_id}/raw/original.mp4
```

In the `videos` table:

```text
raw_video_path = videos/{video_id}/raw/original.mp4
```

The backend can generate a short-lived signed URL when the frontend needs to
view a private asset.

## Why One Table

Because the app only needs to retrieve previously analyzed videos, one table is
enough right now.

The backend workflow becomes:

1. User submits a URL.
2. Backend checks `videos.original_url`.
3. If found, return the saved analysis.
4. If not found, analyze the video.
5. Save one completed row in `videos`.
6. Future requests can reuse that row.

`file_sha256` is optional but useful. It identifies the actual downloaded video
file. Two different URLs can point to the exact same video, and their
`file_sha256` would match.

`processing_status` was removed because incomplete videos are not saved here.
Queue/worker state can live in Celery/Redis or backend logs.

## Similarity Search

The `videos.video_embedding` column stores one whole-video embedding. The helper
in `storage/vector/search.py` compares a new embedding against previously saved
videos using pgvector cosine distance.

This supports:

- finding similar previously analyzed videos
- avoiding repeated analysis for near-duplicates
- basic repost detection without frame-by-frame storage

If RealReel later needs partial-clip detection, then adding a separate table for
frame-level embeddings would make sense. For now, that complexity is removed.

## FastAPI Routes

Mount the router:

```python
from fastapi import FastAPI
from storage.api import router as storage_router

app = FastAPI()
app.include_router(storage_router)
```

Included endpoints:

- `POST /storage/videos`: save a completed analysis
- `GET /storage/videos`: list recent analyzed videos
- `GET /storage/videos/by-url`: find by original URL
- `GET /storage/videos/by-sha256`: find by file hash
- `GET /storage/videos/{video_id}`: get one saved analysis
- `POST /storage/videos/similar`: find similar saved videos by embedding
- `POST /storage/assets/signed-url`: create a signed URL for a private file
- `DELETE /storage/videos/{video_id}`: delete DB row and storage assets

## Why pgvector

pgvector lets Supabase Postgres store and search embeddings directly in the same
database as the saved video analysis rows. That keeps the architecture simple.

FAISS or a dedicated vector database may be useful later, but they add another
system to deploy, sync, back up, and debug. For this stage, pgvector is the right
fit.
