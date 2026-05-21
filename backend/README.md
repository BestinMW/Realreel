# RealReel Backend

Python utilities for local video preprocessing (frame extraction and transcription).

## Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

## Scripts

### Extract frames

Writes every frame as JPG files next to the source video (`{video_name}_frames/`). Prints the output directory path on success.

```bash
python frame_extractor.py path/to/video.mp4
```

### Transcribe audio

Transcribes a local audio file with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and saves JSON to `output_path`.

```bash
python transcribe_audio.py path/to/audio.wav path/to/transcript.json
python transcribe_audio.py audio.wav transcript.json --model base --device cpu
```

The Next.js YouTube pipeline in `frontend/app/api/process-youtube/` uses Node (ffmpeg, OpenAI Whisper API, Tesseract, Gemini) instead of these scripts. Use this folder for standalone or future Python backend work.
