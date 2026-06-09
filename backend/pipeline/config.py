import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
UPLOADS_ROOT = Path(os.environ.get("UPLOADS_ROOT", REPO_ROOT / "tmp" / "uploads"))

FRAME_SAMPLE_RATE = float(os.environ.get("FRAME_SAMPLE_RATE", "1"))
ADAPTIVE_FRAME_SAMPLING = os.environ.get("ADAPTIVE_FRAME_SAMPLING", "true").lower() != "false"
TARGET_SAMPLED_FRAMES = int(os.environ.get("TARGET_SAMPLED_FRAMES", "30"))
MIN_SAMPLED_FRAMES = int(os.environ.get("MIN_SAMPLED_FRAMES", "8"))
MAX_SAMPLED_FRAMES = int(os.environ.get("MAX_SAMPLED_FRAMES", "60"))
KEYFRAME_SCENE_THRESHOLD = float(os.environ.get("KEYFRAME_SCENE_THRESHOLD", "0.35"))
KEYFRAME_INTERVAL_SECONDS = float(os.environ.get("KEYFRAME_INTERVAL_SECONDS", "5"))
MAX_KEYFRAMES_TO_ANALYZE = int(os.environ.get("MAX_KEYFRAMES_TO_ANALYZE", "3"))
MAX_VISUAL_EVENT_FRAMES_TO_ANALYZE = int(
    os.environ.get("MAX_VISUAL_EVENT_FRAMES_TO_ANALYZE", "6")
)
VISUAL_EVENT_WINDOW_RADIUS_FRAMES = int(
    os.environ.get("VISUAL_EVENT_WINDOW_RADIUS_FRAMES", "2")
)
TRANSCRIPTION_LEAD_IN_SECONDS = float(os.environ.get("TRANSCRIPTION_LEAD_IN_SECONDS", "1"))
FAST_PROCESSING_MODE = os.environ.get("FAST_PROCESSING_MODE", "false").lower() == "true"
UPLOAD_RAW_VIDEO = os.environ.get("UPLOAD_RAW_VIDEO", "false").lower() == "true"

STORAGE_BUCKETS = {
    "rawVideos": os.environ.get("RAW_VIDEOS_BUCKET", "raw-videos"),
    "audio": os.environ.get("AUDIO_BUCKET", "audio"),
    "transcripts": os.environ.get("TRANSCRIPTS_BUCKET", "transcripts"),
    "thumbnails": os.environ.get("THUMBNAILS_BUCKET", "thumbnails"),
    "analysis": os.environ.get("ANALYSIS_BUCKET")
    or os.environ.get("TRANSCRIPTS_BUCKET", "transcripts"),
}

OPENAI_TRANSCRIPTION_MODEL = os.environ.get("OPENAI_TRANSCRIPTION_MODEL", "whisper-1")
OPENAI_AUDIO_FILE_LIMIT_BYTES = 25 * 1024 * 1024

OCR_LANGUAGE = os.environ.get("TESSERACT_LANGUAGE", "eng")
MIN_WORD_CONFIDENCE = float(os.environ.get("TESSERACT_MIN_CONFIDENCE", "35"))
OCR_ENABLED = os.environ.get("ENABLE_KEYFRAME_OCR", "true").lower() != "false"

GEMINI_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash-lite")
GEMINI_TIMEOUT_MS = int(os.environ.get("GEMINI_VISION_TIMEOUT_MS", "25000"))
VISION_ENABLED = os.environ.get("ENABLE_KEYFRAME_VISION", "true").lower() != "false"
VISION_PROVIDER = os.environ.get("VISION_PROVIDER", "gemini_api").lower()
VERTEX_AI_PROJECT_ID = os.environ.get("VERTEX_AI_PROJECT_ID", "")
VERTEX_AI_LOCATION = os.environ.get("VERTEX_AI_LOCATION", "us-central1")
VERTEX_AI_GEMINI_MODEL = os.environ.get("VERTEX_AI_GEMINI_MODEL", "gemini-2.5-flash")

CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
