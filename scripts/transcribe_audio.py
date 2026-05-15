import argparse
import json
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Transcribe an audio file with faster-whisper."
    )
    parser.add_argument("audio_path", help="Path to the audio file to transcribe.")
    parser.add_argument("output_path", help="Path where transcript JSON should be saved.")
    parser.add_argument(
        "--model",
        default="base",
        help="faster-whisper model size or local model path. Defaults to base.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Device for inference, such as cpu or cuda. Defaults to cpu.",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="Compute type for faster-whisper. Defaults to int8.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    audio_path = Path(args.audio_path)
    output_path = Path(args.output_path)

    if not audio_path.is_file():
        print(f"Audio file not found: {audio_path}", file=sys.stderr)
        return 1

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "Missing dependency: faster-whisper. Install it with `pip install faster-whisper`.",
            file=sys.stderr,
        )
        return 1

    try:
        model = WhisperModel(
            args.model,
            device=args.device,
            compute_type=args.compute_type,
        )
        segments, info = model.transcribe(str(audio_path), beam_size=5)

        transcript_segments = []
        text_parts = []

        for segment in segments:
            text = segment.text.strip()
            if text:
                text_parts.append(text)

            transcript_segments.append(
                {
                    "id": segment.id,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                }
            )

        payload = {
            "model": args.model,
            "engine": "faster-whisper",
            "language": info.language,
            "language_probability": info.language_probability,
            "duration": info.duration,
            "text": " ".join(text_parts),
            "segments": transcript_segments,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps(payload), flush=True)
        return 0
    except Exception as exc:
        print(f"Transcription failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
