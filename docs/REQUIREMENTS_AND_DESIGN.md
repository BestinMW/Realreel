# Task 2 Worksheet (Submission File)

## Part A: Functionality (2-4 Functionalities Required)

### Functionality 1: Video URL Preview and Submission
- Input:
  - User enters a full video URL in the web UI.
  - Supported examples include YouTube, YouTube Shorts, TikTok, Instagram Reels/posts, Vimeo, or a direct video file URL.
  - User may enable or disable fast processing mode before submitting.
- Output:
  - Embedded preview when the platform supports it, or a ready/validation message when preview is limited.
  - A processing request sent from the frontend to the backend.
- Success:
  - Valid URLs enable the processing button.
  - Preview renders for supported embed/direct video cases.
  - Submitting a valid URL starts a streamed backend processing run.
- Failure/Edge Cases:
  - Empty input -> show a prompt to paste a video link and keep processing disabled.
  - Invalid URL -> show a validation message requiring a full URL including `https://`.
  - Unsupported social preview format -> allow processing but show that preview is limited.
  - Backend unavailable -> show an error explaining that the processor could not be reached.

### Functionality 2: Video Processing and Progress Streaming
- Input:
  - JSON request with `videoUrl` or `youtubeUrl`.
  - Optional `fastProcessingMode` boolean.
- Output:
  - NDJSON progress events with a numeric progress value and stage label.
  - Final `complete` event containing the analysis result, or an `error` event with a message.
- Success:
  - Backend downloads or resolves the video using `yt-dlp`.
  - Backend extracts media artifacts with `ffmpeg`.
  - Frontend displays progress until the run finishes or fails.
  - Completed runs return structured scores and artifact paths.
- Failure/Edge Cases:
  - URL cannot be downloaded -> return a streamed error event with a user-readable message.
  - Required system tools are missing -> health check reports missing tools and processing fails clearly.
  - User disconnects during processing -> backend stops streaming to that request.
  - Fast processing mode is enabled -> skip configured expensive stages while preserving core analysis.

### Functionality 3: Reliability and Risk Analysis
- Input:
  - Downloaded video, sampled frames/keyframes, thumbnail, audio transcript, OCR/vision output, and platform metadata.
- Output:
  - Claim analysis fields such as claim, verdict, confidence, summary, and recommended action.
  - Risk fields such as misleading probability, visual authenticity risk, thumbnail clickbait score, temporal instability, and repost risk.
  - User-facing reliability score and explanation in the frontend.
- Success:
  - Backend returns risk values on a 0-1 scale when each stage is enabled and has enough evidence.
  - Frontend computes reliability as `100 * (1 - max(risk scores))`.
  - User sees a concise score and rationale instead of raw internal diagnostics.
- Failure/Edge Cases:
  - No clear factual claim -> mark claim verdict as `no_clear_claim` or a comparable fallback.
  - Missing transcript, thumbnail, OCR, or vision output -> return partial results instead of failing the whole run when possible.
  - External AI provider timeout or API failure -> include stage-specific error/fallback fields.
  - Low evidence count -> return conservative confidence and explain that evidence is insufficient.

### Functionality 4: Artifact Storage, Repost Detection, and Database Save
- Input:
  - Processed artifacts, video hash, optional embedding/search data, Supabase credentials, and optional `DATABASE_URL`.
- Output:
  - Supabase Storage paths for raw video, audio, transcript, thumbnail, and analysis JSON files when uploads are enabled.
  - Repost fields such as `isRepost`, `repostRisk`, `repostProbability`, rationale, and matches.
  - Optional saved row in `public.videos`.
- Success:
  - Artifacts upload to configured Supabase Storage buckets.
  - If `DATABASE_URL` is configured, repost checks compare the new video against prior saved videos.
  - If database save is enabled, the completed analysis is inserted or updated in Postgres.
- Failure/Edge Cases:
  - Supabase credentials missing -> skip uploads or return clear storage errors depending on the stage.
  - `DATABASE_URL` missing -> skip repost history and database save gracefully.
  - Duplicate or matching content -> return repost match details and an elevated repost risk.
  - Storage/database service unavailable -> preserve local analysis result and report save/upload failure fields.

## Part B: Architecture Mapping
For each functionality, map responsibilities to components.

### Functionality 1 Mapping
- `interface` responsibilities:
  - Render the RealReel URL input, preview area, fast mode toggle, and process button in `frontend/app/page.tsx`.
  - Validate that the input is a non-empty full URL before enabling processing.
  - Detect embeddable platforms and show a preview or preview-limited message.
- `engine` responsibilities:
  - Receive proxied processing requests through FastAPI `POST /process-youtube`.
  - Accept both `videoUrl` and `youtubeUrl` fields for compatibility.
  - Stream clear errors when the processing service cannot handle the request.
- `storage` responsibilities:
  - No direct storage work is required for preview.
  - Storage becomes involved after the processing request produces artifacts or repost data.

### Functionality 2 Mapping
- `interface` responsibilities:
  - Send `POST /api/process-youtube` from the Next.js app.
  - Stream and parse NDJSON progress events from the backend proxy.
  - Display current stage, progress percent, final result, or error message.
- `engine` responsibilities:
  - Use `backend/main.py` to stream responses from `process_youtube_video`.
  - Download the video, extract media assets, run configured pipeline stages, and stop streaming if the user disconnects.
  - Return `progress`, `complete`, or `error` events.
- `storage` responsibilities:
  - Store artifacts created during processing when Supabase credentials are configured.
  - Provide optional existing-video data for repost checks.

### Functionality 3 Mapping
- `interface` responsibilities:
  - Convert returned risk fields into a single reliability score.
  - Show the reliability score, explanation, and any user-facing error state.
  - Avoid exposing raw debug-only details in the main experience.
- `engine` responsibilities:
  - Run transcription, keyframe vision/OCR, temporal analysis, thumbnail analysis, metadata checks, and claim analysis.
  - Normalize risk outputs to 0-1 values.
  - Return partial results when optional stages fail or are disabled.
- `storage` responsibilities:
  - Provide repost history data that contributes to repost risk.
  - Persist score and analysis fields when database save is enabled.

### Functionality 4 Mapping
- `interface` responsibilities:
  - Display storage-related result fields only through user-facing reliability/rationale outputs.
  - Surface backend errors when artifact upload or database save affects the final result.
- `engine` responsibilities:
  - Upload generated files through the storage pipeline.
  - Compute video hashes and call repost/database services.
  - Include storage paths, repost fields, and database status fields in the final response.
- `storage` responsibilities:
  - Manage Supabase Storage buckets for raw video, audio, transcripts, thumbnails, and analysis JSON.
  - Query and update the `public.videos` table.
  - Support repost lookup using hashes and optional embedding similarity.

## Part C: Interface Contracts

### Functionality 1

#### `interface -> engine`
- Function(s):
  - `POST /api/process-youtube` in `frontend/app/api/process-youtube/route.js`
  - Proxies to `POST /process-youtube` in `backend/main.py`
- Input payload:
  - `{ "videoUrl": "https://example.com/video", "fastProcessingMode": false }`
  - Backend also accepts `{ "youtubeUrl": "https://example.com/video" }`
- Return payload/status:
  - `200` with `application/x-ndjson` stream when the backend starts processing.
  - `502` JSON error from the frontend proxy if the backend cannot be reached.
- Failure statuses:
  - Invalid or empty URL is blocked in the interface before submission.
  - Backend unavailable -> `{ "message": "Could not reach processor..." }`
  - Backend processing failure -> streamed `{ "type": "error", "message": "..." }`

#### `engine -> storage`
- Function(s):
  - None for preview-only behavior.
  - Processing requests later call storage functions during artifact upload and repost checks.
- Input payload:
  - None for preview-only behavior.
- Return payload/status:
  - None for preview-only behavior.
- Failure statuses:
  - None for preview-only behavior.

### Functionality 2

#### `interface -> engine`
- Function(s):
  - `fetch("/api/process-youtube", { method: "POST", body })`
  - `process_youtube(payload: ProcessRequest, request: Request)` in `backend/main.py`
- Input payload:
  - `{ "videoUrl": string, "fastProcessingMode": boolean }`
- Return payload/status:
  - Progress event: `{ "type": "progress", "progress": number, "stage": string }`
  - Complete event: `{ "type": "complete", "progress": 100, "stage": string, "result": object }`
  - Error event: `{ "type": "error", "message": string }`
- Failure statuses:
  - Download failure -> streamed error event.
  - Missing `ffmpeg`, `yt-dlp`, or optional `tesseract` -> health check reports missing tools and processing may fail or skip optional OCR.
  - Client disconnect -> engine stops streaming.

#### `engine -> storage`
- Function(s):
  - `upload_pipeline_artifacts(...)` through `backend/pipeline/storage.py`
  - Repost lookup through `storage/services/reposts.py`
  - Database save through `storage/services/db_videos.py`
- Input payload:
  - Local artifact paths, video metadata, video hash, risk scores, transcript/analysis JSON, and configured Supabase/Postgres environment values.
- Return payload/status:
  - Storage paths for uploaded artifacts.
  - Repost match result fields.
  - Database save status and optional saved video id.
- Failure statuses:
  - Missing Supabase credentials -> upload skipped or reported as failed.
  - Missing `DATABASE_URL` -> repost history and database save skipped gracefully.
  - Storage/database unavailable -> final result includes failure or fallback fields.

### Functionality 3

#### `interface -> engine`
- Function(s):
  - Same streaming contract as Functionality 2 through `POST /api/process-youtube`.
- Input payload:
  - Video URL plus optional fast processing mode.
- Return payload/status:
  - Final result can include `claim`, `claimVerdict`, `claimConfidence`, `claimSummary`, `misleadingProbability`, `visualAuthenticityRisk`, `thumbnailClickbaitScore`, `repostRisk`, `recommendedAction`, and rationales.
- Failure statuses:
  - No clear claim -> result uses `no_clear_claim` or an equivalent fallback.
  - Optional analysis stage error -> result contains partial analysis and/or stage-specific error fields.
  - Low evidence -> result returns conservative confidence and explanatory rationale.

#### `engine -> storage`
- Function(s):
  - Repost scoring through `storage/services/reposts.py`
  - Video analysis persistence through `storage/services/db_videos.py`
- Input payload:
  - Video hash, upload metadata, risk scores, claim analysis, transcript summary, and optional embedding/search data.
- Return payload/status:
  - Repost probability/risk, repost rationale, and matched records.
  - Saved database row id/status when enabled.
- Failure statuses:
  - No prior records -> repost risk remains low or unknown.
  - Database disabled/unavailable -> analysis continues without repost history or save.

### Functionality 4

#### `interface -> engine`
- Function(s):
  - Same processing request through `POST /api/process-youtube`.
- Input payload:
  - Video URL and fast mode flag.
- Return payload/status:
  - Final result includes fields such as `rawVideoPath`, `audioPath`, `transcriptPath`, `thumbnailPath`, `claimAnalysisPath`, `isRepost`, `repostRisk`, `repostMatches`, `databaseSaveOk`, and `databaseVideoId`.
- Failure statuses:
  - Upload failures -> final result includes missing paths or upload error fields.
  - Database save failures -> final result includes failed database status while preserving analysis output.

#### `engine -> storage`
- Function(s):
  - Supabase Storage upload helpers in `storage/assets/supabase.py` and `backend/pipeline/storage.py`.
  - Repost service functions in `storage/services/reposts.py`.
  - Database video service functions in `storage/services/db_videos.py`.
- Input payload:
  - Bucket names, artifact file paths, video hash, video URL, metadata, risk scores, and analysis summaries.
- Return payload/status:
  - Uploaded artifact paths.
  - Repost match list and risk fields.
  - Insert/update result for `public.videos`.
- Failure statuses:
  - Supabase bucket or credential issue -> upload failure or skipped upload.
  - Duplicate/matching content -> repost match details returned.
  - Postgres connection issue -> database save skipped/failed without blocking the user-facing analysis.
