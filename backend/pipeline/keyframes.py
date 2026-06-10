from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .config import GEMINI_MODEL, MAX_FRAME_ANALYSIS_WORKERS
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
    """Run OCR and vision analysis on keyframes and return the final JSON result.

    Args:
        keyframe_paths (list[Path]): Paths to keyframe image files to analyze.
        keyframe_timestamps (list[float | None]): Timestamp in seconds for each
            keyframe, aligned by index with ``keyframe_paths``.
        output_path (Path): File path where the combined analysis JSON is written.
        on_progress (Callable[[dict], None] | None): Optional callback invoked with
            progress payloads from ``analyze_keyframes_stream``.

    Returns:
        dict: Combined keyframe analysis document with ``schemaVersion``,
            ``generatedAt``, ``providerVersions``, ``frameCount``, and ``frames``.

    Raises:
        RuntimeError: When the streaming analysis does not produce a result event.
    """
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
    """Stream OCR and vision analysis progress and the final keyframe result.

    Args:
        keyframe_paths (list[Path]): Paths to keyframe image files to analyze.
        keyframe_timestamps (list[float | None]): Timestamp in seconds for each
            keyframe, aligned by index with ``keyframe_paths``.
        output_path (Path): File path where the combined analysis JSON is written.

    Returns:
        Generator[dict[str, Any], None, None]: Yields ``{"kind": "progress",
        "payload": {...}}`` events during analysis and a final
        ``{"kind": "result", "payload": <analysis dict>}`` event.
    """
    yield {
        "kind": "progress",
        "payload": {
            "index": 0,
            "total": len(keyframe_paths),
            "frame": "Running OCR and vision",
        },
    }

    frames_by_index: dict[int, dict[str, Any]] = {}
    max_workers = max(1, min(MAX_FRAME_ANALYSIS_WORKERS, len(keyframe_paths) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _analyze_single_keyframe,
                index=index,
                frame_path=frame_path,
                keyframe_timestamps=keyframe_timestamps,
            ): (index, frame_path)
            for index, frame_path in enumerate(keyframe_paths)
        }

        for future in as_completed(futures):
            index, frame_path = futures[future]
            yield {
                "kind": "progress",
                "payload": {
                    "index": index + 1,
                    "total": len(keyframe_paths),
                    "frame": frame_path.name,
                },
            }
            frames_by_index[index] = future.result()

    frames = [frames_by_index[index] for index in sorted(frames_by_index)]

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


def _analyze_single_keyframe(
    *,
    index: int,
    frame_path: Path,
    keyframe_timestamps: list[float | None],
) -> dict[str, Any]:
    """Analyze one keyframe with OCR, vision, and cross-modal hints.

    Args:
        index (int): Zero-based index of the keyframe in the input list.
        frame_path (Path): Path to the keyframe image file.
        keyframe_timestamps (list[float | None]): Timestamps aligned to all keyframes.

    Returns:
        dict[str, Any]: Per-frame record with ``frame``, ``timestamp``,
            ``timestampSeconds``, ``ocr``, ``vision``, and ``hints`` fields.
    """
    ocr = analyze_frame_ocr(frame_path)
    vision = analyze_frame_with_gemini(
        frame_path,
        ocr_summary=format_ocr_summary(ocr.get("indicators") or {}),
    )
    timestamp_seconds = (
        keyframe_timestamps[index] if index < len(keyframe_timestamps) else None
    )

    return {
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
