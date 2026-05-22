import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
UPLOADS_ROOT = Path(os.environ.get("UPLOADS_ROOT", REPO_ROOT / "tmp" / "uploads"))

FRAME_SAMPLE_RATE = float(os.environ.get("FRAME_SAMPLE_RATE", "1"))
KEYFRAME_SCENE_THRESHOLD = float(os.environ.get("KEYFRAME_SCENE_THRESHOLD", "0.35"))
MAX_KEYFRAMES_TO_ANALYZE = int(os.environ.get("MAX_KEYFRAMES_TO_ANALYZE", "3"))
TRANSCRIPTION_LEAD_IN_SECONDS = float(os.environ.get("TRANSCRIPTION_LEAD_IN_SECONDS", "1"))

STORAGE_BUCKETS = {
    "rawVideos": os.environ.get("RAW_VIDEOS_BUCKET", "raw-videos"),
    "audio": os.environ.get("AUDIO_BUCKET", "audio"),
    "transcripts": os.environ.get("TRANSCRIPTS_BUCKET", "transcripts"),
    "analysis": os.environ.get("ANALYSIS_BUCKET")
    or os.environ.get("TRANSCRIPTS_BUCKET", "transcripts"),
}

OPENAI_TRANSCRIPTION_MODEL = os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
OPENAI_AUDIO_FILE_LIMIT_BYTES = 25 * 1024 * 1024

OCR_LANGUAGE = os.environ.get("TESSERACT_LANGUAGE", "eng")
MIN_WORD_CONFIDENCE = float(os.environ.get("TESSERACT_MIN_CONFIDENCE", "35"))
OCR_ENABLED = os.environ.get("ENABLE_KEYFRAME_OCR", "true").lower() != "false"

GEMINI_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash-lite")
GEMINI_TIMEOUT_MS = int(os.environ.get("GEMINI_VISION_TIMEOUT_MS", "8000"))
VISION_ENABLED = os.environ.get("ENABLE_KEYFRAME_VISION", "true").lower() != "false"

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
