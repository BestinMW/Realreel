# RealReel Workload Report

## Team Members
- Parsa Tehrani
- Bestin Watts

## Workload Split

### Parsa Tehrani
- Defined the RealReel project concept and core goal: analyzing social/video URLs for reliability, misleading context, visual authenticity risk, thumbnail clickbait, and repost history.
- Built and refined the main user-facing workflow in the frontend:
  - URL input and validation
  - video preview behavior
  - fast processing mode toggle
  - progress display
  - reliability score and explanation output
- Removed the old debug page from the app so users only see the polished main experience.
- Added README execution instructions:
  - dependency check command
  - backend setup and startup
  - frontend setup and startup
  - required environment files
  - test commands
- Helped define the project requirements and design direction.

### Bestin Watts
- Developed and organized the backend processing architecture:
  - FastAPI processing endpoint
  - video download and metadata handling
  - audio extraction and transcription flow
  - frame/keyframe extraction
  - temporal consistency analysis
  - OCR and vision analysis
  - claim analysis
  - thumbnail clickbait analysis
  - repost assessment
- Implemented storage-related functionality:
  - Supabase Storage artifact upload paths
  - database save helpers
  - repost lookup helpers
  - vector search support
- Created the formal requirements/design worksheet at:
  - `docs/REQUIREMENTS_AND_DESIGN.md`
- Expanded automated test coverage across backend, storage, and interface behavior.
- Added mocked unit tests for external-service-heavy paths, including:
  - OpenAI claim analysis
  - Gemini/Vertex vision analysis
  - yt-dlp download behavior
  - ffmpeg/ffprobe media helpers
  - Supabase upload wrappers
  - database sync bridge behavior

## Shared Work
- Reviewed the project structure and aligned frontend, backend, storage, and documentation into one coherent workflow.
- Verified local test coverage using:

```powershell
C:\Users\tehra\AppData\Local\Python\bin\python.exe -m pytest --cov=backend --cov=storage --cov-report=term-missing tests/
```

- Increased test coverage from `47%` to `90%`.
- Confirmed the final suite result:
  - `151 passed`
  - `90%` total coverage

## Final Deliverables
- Main RealReel web app experience
- Backend video-processing pipeline
- Supabase/Postgres storage support
- README with execution instructions
- Requirements and design worksheet
- Expanded automated test suite
- Removed debug page
