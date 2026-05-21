# RealReel Frontend

Next.js app for entering and previewing video URLs.

## Getting Started

```bash
npm install
npm run dev
```

Open http://localhost:3000 to view the app.

## Video Processing Setup

Create `frontend/.env.local` from `.env.local.example`.

Required storage variables:

```env
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
RAW_VIDEOS_BUCKET=raw-videos
AUDIO_BUCKET=audio
TRANSCRIPTS_BUCKET=transcripts
ANALYSIS_BUCKET=transcripts
```

Required AI variables:

```env
OPENAI_API_KEY=...
OPENAI_TRANSCRIPTION_MODEL=whisper-1
GEMINI_API_KEY=...
GEMINI_VISION_MODEL=gemini-2.5-flash-lite
```

Frame extraction controls:

```env
FRAME_SAMPLE_RATE=1
KEYFRAME_SCENE_THRESHOLD=0.35
TESSERACT_LANGUAGE=eng
TESSERACT_MIN_CONFIDENCE=35
```

The route creates two temporary folders per job:

```text
frames/     1 FPS sampled frames for frame-by-frame analysis
keyframes/  scene-change frames for OCR and Gemini vision analysis
```

Both folders are deleted after processing. The uploaded JSON artifact is:

```text
videos/{jobId}/analysis/keyframe-analysis.json
```

Cost notes:

- OpenAI transcription is billed by audio duration.
- Gemini vision is billed per image request/token usage, so lowering
  `KEYFRAME_SCENE_THRESHOLD` can increase cost by producing more keyframes.
- Tesseract OCR runs locally through `tesseract.js`; it does not call a paid API.
