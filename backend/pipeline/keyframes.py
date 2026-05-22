import json
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import GEMINI_MODEL
from .indicators import (
    SCHEMA_VERSION,
    cross_modal_hints,
    format_ocr_summary,
    seconds_to_timestamp,
)
from .ocr import analyze_frame as analyze_frame_ocr
from .vision import analyze_frame_with_gemini


def analyze_keyframes(
    *,
    keyframe_paths: list[Path],
    keyframe_timestamps: list[float | None],
    output_path: Path,
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    result = None
    for event in analyze_keyframes_stream(
        keyframe_paths=keyframe_paths,
        keyframe_timestamps=keyframe_timestamps,
        output_path=output_path,
    ):
        if event.get("kind") == "progress":
            if on_progress:
                on_progress(event["payload"])
        elif event.get("kind") == "result":
            result = event["payload"]
    if result is None:
        raise RuntimeError("Keyframe analysis did not produce a result.")
    return result


def analyze_keyframes_stream(
    *,
    keyframe_paths: list[Path],
    keyframe_timestamps: list[float | None],
    output_path: Path,
) -> Generator[dict[str, Any], None, None]:
    yield {
        "kind": "progress",
        "payload": {
            "index": 0,
            "total": len(keyframe_paths),
            "frame": "Running OCR and vision",
        },
    }

    frames = []
    for index, frame_path in enumerate(keyframe_paths):
        yield {
            "kind": "progress",
            "payload": {
                "index": index + 1,
                "total": len(keyframe_paths),
                "frame": frame_path.name,
            },
        }

        ocr = analyze_frame_ocr(frame_path)
        vision = analyze_frame_with_gemini(
            frame_path,
            ocr_summary=format_ocr_summary(ocr.get("indicators") or {}),
        )
        timestamp_seconds = (
            keyframe_timestamps[index]
            if index < len(keyframe_timestamps)
            else None
        )

        frames.append(
            {
                "frame": frame_path.name,
                "timestamp": seconds_to_timestamp(timestamp_seconds),
                "timestampSeconds": timestamp_seconds,
                "ocr": {
                    "ok": ocr["ok"],
                    "text": ocr["text"],
                    "indicators": ocr["indicators"],
                    "confidence": ocr["confidence"],
                    "error": ocr["error"],
                },
                "vision": {
                    "ok": vision["ok"],
                    "indicators": vision["indicators"],
                    "error": vision["error"],
                },
                "hints": cross_modal_hints(
                    ocr.get("indicators") or {},
                    vision.get("indicators") or {},
                ),
            }
        )

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "providerVersions": {
            "ocr": "pytesseract",
            "vision": GEMINI_MODEL,
        },
        "frameCount": len(frames),
        "frames": frames,
    }
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    yield {"kind": "result", "payload": result}
