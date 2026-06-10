# Task 2 Worksheet (Submission File)

## Part A: Functionality

### Functionality 1: Video URL Preview and Submission
- Input:
  - User enters a full video URL in the web UI (YouTube, YouTube Shorts, TikTok, Instagram, Vimeo, or direct video link)
  - Optional fast processing mode toggle
- Output:
  - Embedded preview when the platform supports it, or a ready/validation message when preview is limited
  - Enabled process button when the URL is valid
- Success:
  - Valid URLs enable the processing button
  - Preview renders for supported embed or direct-video cases
  - Submitting a valid URL starts a proxied backend processing run
- Failure/Edge Cases:
  - Empty input -> prompt to paste a video link; processing stays disabled
  - Invalid URL -> validation message requiring a full URL including `https://`
  - Unsupported social preview format -> allow processing but show that preview is limited
  - Backend unavailable -> error explaining the processor could not be reached

### Functionality 2: Video Processing and Progress Streaming
- Input:
  - JSON request with `videoUrl` or `youtubeUrl`
  - Optional `fastProcessingMode` boolean
- Output:
  - NDJSON progress events with numeric progress and stage label
  - Final `complete` event with the analysis result, or an `error` event with a message
- Success:
  - Backend downloads the video via `yt-dlp` and prepares media with `ffmpeg`
  - Frontend displays progress until the run finishes or fails
  - Completed runs hand off to analysis and persistence stages (Functionality 3)
- Failure/Edge Cases:
  - URL cannot be downloaded -> streamed error event with a user-readable message
  - Missing `ffmpeg` or `yt-dlp` -> health check reports missing tools; processing may fail
  - Client disconnects during processing -> engine stops streaming to that request
  - Fast processing mode enabled -> skips visual events, metadata rules, thumbnail clickbait, and raw video upload while preserving core analysis

### Functionality 3: Reliability Analysis, Repost Detection, and Persistence
- Input:
  - Downloaded video, audio transcript, sampled keyframes, thumbnail, OCR/vision output, platform metadata
  - Processed artifacts, video hash (`file_sha256`), optional embedding, Supabase credentials, and optional `DATABASE_URL`
- Output:
  - Misinformation score (`misleadingProbability`, 0.0–1.0)
  - AI-likelihood score (`visualAuthenticityRisk`, 0.0–1.0)
  - Additional risk fields: thumbnail clickbait score, repost risk, claim verdict, confidence
  - User-facing reliability score (0–100%) computed as `100 * (1 - max(risk scores))`
  - List of detected signals and explanations (claim summary, visual authenticity rationale, thumbnail/repost rationales)
  - Supabase Storage paths for raw video, audio, transcript, thumbnail, and analysis JSON when uploads are enabled
  - Repost fields: `isRepost`, `repostRisk`, `repostProbability`, rationale, and matches
  - Optional saved row in `public.videos` with scores and `platform_upload_date`
- Success:
  - Successful extraction of video metadata and transcript
  - Backend normalizes risk outputs to 0–1 when each stage has enough evidence
  - User sees a concise score and rationale instead of raw internal diagnostics
  - Artifacts upload to configured Supabase Storage buckets
  - When `DATABASE_URL` is set, repost checks compare the new video against prior saved videos (SHA-256 hash match from the pipeline; pgvector embedding similarity is supported in storage but not yet passed from the engine)
  - Completed analysis is inserted or updated in Postgres when database save is enabled
- Failure/Edge Cases:
  - No clear factual claim -> claim verdict `no_clear_claim` or equivalent fallback
  - No transcript or captions -> partial analysis; transcript-dependent stages may be skipped or weakened
  - Optional stage failure (OCR, vision, claim API) -> partial result with stage-specific fallback fields
  - Low evidence count -> conservative confidence and explanatory rationale
  - Supabase credentials missing -> skip uploads or report storage errors in result fields
  - `DATABASE_URL` missing -> skip repost history and database save gracefully
  - Duplicate or matching content from an earlier upload -> repost match details and elevated repost risk
  - Storage or database unavailable -> preserve analysis result and report save/upload failure fields

### Functionality 4: Analysis Feedback
- Input:
  - Can choose whether analysis was `Correct` or `Incorrect`
  - Optional comment
  - Video identifier (`databaseVideoId`, platform id, source URL, or submitted URL)
- Output:
  - Message `feedback submitted`
- Success:
  - Successful feedback save to `public.analysis_feedback`
- Failure/Edge Cases:
  - Unable to record feedback -> `feedback to storage failure`
  - Missing required fields (`vid_id` or `label`) -> `empty feedback`

## Part B: Architecture Mapping
For each functionality, map responsibilities to components.

**Package boundaries:** `backend/pipeline/` contains analysis-only code. `backend/adapters/` is the only engine package that imports the top-level `storage` package (feedback, repost assessment, Postgres persistence, and Supabase artifact uploads). `storage/` never imports `backend/`.

### Functionality 1 Mapping
- `interface` responsibilities:
  - Render URL input, preview area, fast mode toggle, and process button in `frontend/app/page.tsx`
  - Validate non-empty full URL before enabling processing via `getPreviewSource()` and `isValidUrl()`
  - Detect embeddable platforms and show iframe preview, direct video, or preview-limited message
- `engine` responsibilities:
  - None for preview-only behavior
  - Accept processing requests once the user submits through `POST /process-youtube` (Functionality 2)
- `storage` responsibilities:
  - None for preview-only behavior

### Functionality 2 Mapping
- `interface` responsibilities:
  - Send `POST /api/process-youtube` from the Next.js app
  - Stream and parse NDJSON progress events from the backend proxy
  - Display current stage, progress percent, or error message during the run
- `engine` responsibilities:
  - Expose `POST /process-youtube` in `backend/main.py`
  - Download video and prepare media in `backend/pipeline/download.py` and `backend/pipeline/media.py`
  - Orchestrate pipeline stages in `backend/pipeline/process.py`
  - Return `progress`, `complete`, or `error` events; stop streaming if the client disconnects
- `storage` responsibilities:
  - None during download and early pipeline stages
  - Invoked indirectly through `backend/adapters/` when analysis and persistence stages run (Functionality 3)

### Functionality 3 Mapping
- `interface` responsibilities:
  - Receive the final `complete` result from the streamed processing response
  - Convert risk fields into a reliability score in `getReliabilityScore()`
  - Build user-facing explanation text in `getReliabilityExplanation()`
  - Display reliability score, rationales, and persistence-related outcomes without exposing raw debug-only fields
- `engine` responsibilities:
  - Run analysis stages in `backend/pipeline/`: media prep (`media.py`), transcription (`transcribe.py`), temporal analysis (`temporal.py`), visual events (`visual_events.py`), keyframe vision/OCR (`keyframes.py`, `vision.py`, `ocr.py`), metadata rules (`metadata_analyzer.py`), thumbnail clickbait (`thumbnail.py`), and claim analysis (`claim_analysis.py`)
  - Orchestrate the run in `backend/pipeline/process.py`; normalize risk outputs to 0–1 values and return partial results when optional stages fail
  - Delegate external I/O to `backend/adapters/`:
    - `adapters/reposts.py` — repost assessment (`assess_repost_history`)
    - `adapters/object_storage.py` — Supabase artifact uploads (`upload_to_supabase_storage`, `ensure_storage_buckets`)
    - `adapters/persistence.py` — database save (`persist_analysis_record`)
  - Include scores, rationales, repost fields, storage paths, and `databaseSaveOk` / `databaseVideoId` in the final response
- `storage` responsibilities:
  - Repost lookup and rules in `storage/services/reposts.py` (hash match; pgvector similarity when an embedding is supplied)
  - Map pipeline output to a `VideoCreate` row in `storage/services/db_videos.py`; upsert via `storage/services/videos.py`
  - Persist feedback in `public.analysis_feedback` via `storage/services/feedback.py`
  - Optional standalone storage API (`storage/api/routes.py`) using `storage/assets/supabase.py` for signed URLs and service-layer uploads (separate from the engine's httpx upload adapter)

### Functionality 4 Mapping
- `interface` responsibilities:
  - Retrieve user feedback through Correct/Incorrect controls and optional comment in `frontend/app/page.tsx`
  - Submit feedback through `POST /api/feedback` in `frontend/app/api/feedback/route.js`
  - Show `feedback submitted` or error message to the user
- `engine` responsibilities:
  - Expose `POST /feedback` in `backend/main.py`
  - Validate required fields and label format in `validate_feedback_submission()` (`backend/pipeline/feedback.py`)
  - Persist valid feedback through `submit_feedback()` (`backend/adapters/feedback.py`); do not persist feedback in the interface layer
- `storage` responsibilities:
  - Persist feedback records in `public.analysis_feedback` via `save_feedback()` in `storage/services/feedback.py`
  - Expose `POST /storage/feedback` in `storage/api/routes.py` for direct storage API access

## Part C: Interface Contracts

### Functionality 1 Contracts

#### `interface -> engine`
- Function(s):
  - None for preview-only behavior
  - Submission uses `fetch("/api/process-youtube")` (Functionality 2)
- Input payload:
  - None for preview-only behavior
- Return payload/status:
  - None for preview-only behavior
- Failure statuses:
  - Invalid or empty URL blocked in the interface before submission
  - Backend unavailable on submit -> `{ "message": "Could not reach processor..." }`

#### `engine -> storage`
- Function(s):
  - None
- Input payload:
  - None
- Return payload/status:
  - None
- Failure statuses:
  - None

### Functionality 2 Contracts

#### `interface -> engine`
- Function(s):
  - `fetch("/api/process-youtube", { method: "POST", body })` in `frontend/app/page.tsx`
  - `process_youtube(payload, request)` in `backend/main.py`
  - `process_youtube_video(video_url)` in `backend/pipeline/process.py`
- Input payload:
  ```json
  { "videoUrl": "https://www.youtube.com/watch?v=example", "fastProcessingMode": false }
  ```
  - Backend also accepts `{ "youtubeUrl": "https://www.youtube.com/watch?v=example" }`
- Return payload/status:
  - Progress: `{ "type": "progress", "progress": 42, "stage": "Transcribing" }`
  - Complete: `{ "type": "complete", "progress": 100, "stage": "Complete", "result": { ... } }`
  - Error: `{ "type": "error", "message": "..." }`
- Failure statuses:
  - Download failure -> streamed error event
  - Missing system tools -> reported by `GET /health`; processing may fail or skip optional OCR
  - Client disconnect -> engine stops streaming

#### `engine -> storage`
- Function(s):
  - None during download and streaming setup
  - Persistence contracts are defined under Functionality 3 at pipeline completion
- Input payload:
  - None
- Return payload/status:
  - None
- Failure statuses:
  - None

### Functionality 3 Contracts

#### `interface -> engine`
- Function(s):
  - Same streaming contract as Functionality 2 through `POST /api/process-youtube`
  - `getReliabilityScore()` and `getReliabilityExplanation()` in `frontend/app/page.tsx`
- Input payload:
  - Video URL plus optional fast processing mode
- Return payload/status:
  - Final `result` includes analysis scores and rationales:
    - `claim`, `claimVerdict`, `claimConfidence`, `claimSummary`
    - `misleadingProbability`, `visualAuthenticityRisk`, `visualAuthenticitySignals`
    - `thumbnailClickbaitScore`, `repostRisk`, `recommendedAction`, and related rationales
  - Final `result` includes persistence and repost fields:
    - `rawVideoPath`, `audioPath`, `transcriptPath`, `thumbnailPath`, `claimAnalysisPath`
    - `isRepost`, `repostRisk`, `repostMatches`, `databaseSaveOk`, `databaseVideoId`
  - Frontend derives reliability score from the risk fields
- Failure statuses:
  - No clear claim -> `claimVerdict: "no_clear_claim"`
  - Optional analysis stage error -> partial analysis and/or stage-specific fallback fields
  - Low evidence -> conservative confidence and explanatory rationale
  - Upload failures -> missing paths or upload error fields in the result
  - Database save failures -> `databaseSaveOk: false` while preserving analysis output

#### `engine -> storage`
- Function(s):
  - **Adapter layer** (`backend/adapters/`, called from `backend/pipeline/process.py`):
    - `upload_to_supabase_storage(...)` and `ensure_storage_buckets(...)` in `adapters/object_storage.py`
    - `assess_repost_history(...)` in `adapters/reposts.py`
    - `persist_analysis_record(...)` in `adapters/persistence.py`
  - **Storage layer** (imported only by adapters):
    - `run_repost_assessment_sync(...)` in `storage/services/reposts.py`
    - `build_db_video_payload(...)` and `persist_db_video_sync(...)` in `storage/services/db_videos.py`
    - `persist_analyzed_video(session, payload)` in `storage/services/videos.py`
  - **Optional standalone storage API** (not used by the default processing stream):
    - `storage_service.upload(...)` in `storage/assets/supabase.py`
    - `POST /storage/videos` in `storage/api/routes.py`
- Input payload:
  ```json
  {
    "original_url": "https://www.youtube.com/watch?v=example",
    "file_sha256": "abc123...",
    "platform_upload_date": "2024-06-15",
    "ai_generated_score": 0.10,
    "misleading_context_score": 0.80,
    "repost_probability": 0.65,
    "overall_risk_score": 0.80,
    "credibility_score": 0.20,
    "confidence": 0.75,
    "reasons": {
      "claim": { "verdict": "mixed", "summary": "..." },
      "scores": {
        "misleadingProbability": 0.80,
        "visualAuthenticityRisk": 0.10
      },
      "repost": { "isRepost": true, "matches": [] }
    }
  }
  ```
- Return payload/status:
  - `{ "ok": true, "videoId": "00000000-0000-0000-0000-000000000001", "error": null }`
  - Uploaded artifact paths and repost match list
- Failure statuses:
  - Missing Supabase credentials -> upload skipped or reported as failed
  - Missing `DATABASE_URL` -> repost history and database save skipped gracefully
  - `{ "status": "storage_error", "message": "unable to save to storage" }`
  - Postgres connection issue -> database save skipped/failed without blocking user-facing analysis

### Functionality 4 Contracts

#### `interface -> engine`
- Function(s):
  - `fetch("/api/feedback")` in `frontend/app/page.tsx`
  - `POST /feedback` in `backend/main.py`
  - `submit_feedback(vid_id, label, comment)` in `backend/adapters/feedback.py`
  - `validate_feedback_submission(vid_id, label, comment)` in `backend/pipeline/feedback.py` (validation only; no storage imports)
- Input payload:
  ```json
  {
    "vid_id": "example1",
    "label": "Incorrect",
    "comment": "AI score is high when the video is clearly not AI."
  }
  ```
- Return payload/status:
  - `{ "status": "success", "message": "feedback submitted" }`
- Failure statuses:
  - `{ "status": "missing_fields", "message": "empty feedback" }`
  - `{ "status": "storage_error", "message": "feedback to storage failure" }`

#### `engine -> storage`
- Function(s):
  - `submit_feedback(...)` in `backend/adapters/feedback.py` forwards to:
    - `save_feedback_sync(feedback_data)` in `storage/services/feedback.py`
  - Optional direct storage API (not used by the default feedback proxy):
    - `save_feedback(session, feedback_data)` in `storage/services/feedback.py`
    - `POST /storage/feedback` in `storage/api/routes.py`
- Input payload:
  ```json
  {
    "vid_id": "example1",
    "label": "Incorrect",
    "comment": "AI score is high when the video is clearly not AI."
  }
  ```
- Return payload/status:
  - `{ "status": "success", "id": "feedback1" }`
- Failure statuses:
  - `{ "status": "storage_error", "message": "unable to save to storage" }`
