# RealReel Workload Report

## Team Members
- Parsa Tehrani
- Bestin Watts

## Workload Split

### Parsa Tehrani
- Worked on the RealReel project concept and user-facing product direction:
  - reliability scoring for social/video URLs
  - misleading-context detection
  - visual authenticity risk
  - thumbnail clickbait risk
  - repost-history awareness
- Contributed to the frontend workflow:
  - URL input and validation
  - video preview behavior
  - fast processing mode toggle
  - processing progress display
  - final reliability score and explanation UI
- Contributed to backend pipeline behavior:
  - request flow between the frontend proxy and FastAPI processor
  - progress-streaming behavior for processing stages
  - fast processing mode behavior and skipped-stage handling
  - reliability-score fields returned from backend results
- Worked on media and analysis pipeline features:
  - frame/keyframe handling
  - temporal consistency outputs
  - thumbnail and transcript result fields
  - user-facing summary/rationale fields
- Added and reviewed documentation:
  - README execution instructions
  - environment setup notes
  - requirements/design worksheet content
- Contributed to test coverage:
  - interface behavior tests
  - backend processing-flow tests
  - mocked tests for fast-mode and non-fast-mode processing
  - verification of the final coverage command and output

### Bestin Watts
- Helped build and organize the backend architecture:
  - FastAPI processing endpoint
  - video URL parsing and platform handling
  - video download metadata flow
  - audio extraction and transcription flow
  - claim-analysis result shaping
- Contributed to visual and authenticity analysis:
  - OCR/vision result structure
  - Gemini/Vertex response handling
  - temporal/event-window analysis helpers
  - thumbnail clickbait analysis behavior
- Worked on storage and persistence features:
  - Supabase Storage artifact paths
  - raw video/audio/transcript/analysis upload flow
  - database save helpers
  - repost lookup helpers
  - vector search support
- Improved project documentation:
  - requirements/design worksheet formatting
  - architecture mapping
  - interface contract descriptions
  - README links to project documentation
- Contributed to testing coverage:
  - storage and repost tests
  - backend helper tests
  - mocked external-service tests for OpenAI, Gemini/Vertex, yt-dlp, ffmpeg, Supabase, and database behavior
  - coverage cleanup for edge cases and failure paths

## Shared Work
- Integrated the frontend, backend, and storage layers into one coherent workflow.
- Removed the old debug page and kept the app focused on the main user experience.
- Reviewed and refined the requirements/design document:
  - Part A: functionality
  - Part B: architecture mapping
  - Part C: interface contracts
- Expanded the automated test suite together across interface, engine, and storage
- Covered test gaps to get coverage to '90%'

## Final Deliverables
- Main RealReel web app
- Backend video-processing pipeline
- Supabase/Postgres storage/db support
- README with execution instructions
- Requirements and design worksheet
- Expanded automated test suite
