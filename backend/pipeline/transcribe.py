import os
from pathlib import Path

import httpx

from .config import OPENAI_AUDIO_FILE_LIMIT_BYTES, OPENAI_TRANSCRIPTION_MODEL


def transcribe_audio_with_openai(audio_path: Path) -> dict:
    """Transcribe an audio file with the OpenAI Audio Transcriptions API.

    Args:
        audio_path (Path): Path to a WAV audio file within OpenAI's upload size limit.

    Returns:
        dict: OpenAI verbose JSON transcription payload, including text and timing fields.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "OpenAI transcription is not configured. Set OPENAI_API_KEY."
        )

    file_size = audio_path.stat().st_size
    if file_size > OPENAI_AUDIO_FILE_LIMIT_BYTES:
        raise RuntimeError(
            "The extracted audio is larger than OpenAI's 25 MB transcription upload limit."
        )

    with httpx.Client(timeout=300.0) as client:
        with audio_path.open("rb") as audio_file:
            response = client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                data={
                    "model": OPENAI_TRANSCRIPTION_MODEL,
                    "response_format": "verbose_json",
                },
                files={"file": ("audio.wav", audio_file, "audio/wav")},
            )

    if response.status_code >= 400:
        raise RuntimeError(f"Failed to transcribe audio with OpenAI: {response.text}")

    return response.json()
