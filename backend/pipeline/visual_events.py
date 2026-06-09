import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    FRAME_SAMPLE_RATE,
    GEMINI_MODEL,
    MAX_FRAME_ANALYSIS_WORKERS,
    MAX_VISUAL_EVENT_FALLBACK_FRAMES,
    MAX_VISUAL_EVENT_FRAMES_TO_ANALYZE,
    VISUAL_EVENT_WINDOW_RADIUS_FRAMES,
)
from .indicators import SCHEMA_VERSION, seconds_to_timestamp
from .vision import (
    analyze_event_window_consistency,
    analyze_frame_authenticity,
    analyze_frame_with_gemini,
)


def analyze_visual_events(
    *,
    frame_paths: list[Path],
    temporal_analysis: dict,
    output_path: Path,
) -> dict[str, Any]:
    selected_frames = _select_event_frames(
        frame_paths=frame_paths,
        temporal_analysis=temporal_analysis,
        limit=MAX_VISUAL_EVENT_FRAMES_TO_ANALYZE,
        window_radius=VISUAL_EVENT_WINDOW_RADIUS_FRAMES,
    )
    max_workers = max(1, min(MAX_FRAME_ANALYSIS_WORKERS, len(selected_frames) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        frames = list(executor.map(_analyze_selected_event_frame, selected_frames))

    event_window_consistency = analyze_event_window_consistency(frames)
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "providerVersions": {
            "vision": GEMINI_MODEL,
            "selection": "temporal-event-window-plus-limited-fallback-v2",
        },
        "frameSamplingRate": FRAME_SAMPLE_RATE,
        "frameCount": len(frames),
        "maxFrames": MAX_VISUAL_EVENT_FRAMES_TO_ANALYZE,
        "fallbackMaxFrames": MAX_VISUAL_EVENT_FALLBACK_FRAMES,
        "windowRadiusFrames": VISUAL_EVENT_WINDOW_RADIUS_FRAMES,
        "eventWindowConsistency": event_window_consistency,
        "summary": _summarize(frames),
        "frames": frames,
    }
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _analyze_selected_event_frame(selected_frame: dict[str, Any]) -> dict[str, Any]:
    frame_path = selected_frame["path"]
    frame_index = selected_frame["index"]
    timestamp_seconds = _timestamp_for_index(frame_index)
    vision = analyze_frame_with_gemini(
        frame_path,
        ocr_summary=(
            "sampled frame event-window scan; OCR not run for this frame; "
            f"selectionReason={selected_frame['reason']}; "
            f"windowCenter={selected_frame.get('windowCenterFrame') or 'none'}"
        ),
    )
    authenticity = analyze_frame_authenticity(frame_path)
    indicators = vision.get("indicators") or {}
    return {
        "frame": frame_path.name,
        "timestamp": seconds_to_timestamp(timestamp_seconds),
        "timestampSeconds": timestamp_seconds,
        "selectionReason": selected_frame["reason"],
        "windowCenterFrame": selected_frame.get("windowCenterFrame"),
        "windowOffsetFrames": selected_frame.get("windowOffsetFrames"),
        "sourceComparison": selected_frame.get("sourceComparison"),
        "vision": {
            "ok": vision.get("ok"),
            "indicators": indicators,
            "error": vision.get("error"),
        },
        "authenticity": authenticity,
    }


def _select_event_frames(
    *,
    frame_paths: list[Path],
    temporal_analysis: dict,
    limit: int,
    window_radius: int,
) -> list[dict[str, Any]]:
    if not frame_paths or limit <= 0:
        return []

    by_name = {path.name: index for index, path in enumerate(frame_paths)}
    selected_by_index: dict[int, dict[str, Any]] = {}
    safe_radius = max(0, window_radius)

    suspicious = sorted(
        temporal_analysis.get("comparisons", []) or [],
        key=lambda item: item.get("instabilityScore") or 0,
        reverse=True,
    )
    for comparison in suspicious:
        if not comparison.get("riskSignals"):
            continue

        pair_indexes = [
            index
            for name in (comparison.get("fromFrame"), comparison.get("toFrame"))
            if (index := by_name.get(name)) is not None
        ]
        if not pair_indexes:
            continue

        center_index = round(sum(pair_indexes) / len(pair_indexes))
        for index in _window_indexes(
            center_index=center_index,
            frame_count=len(frame_paths),
            radius=safe_radius,
        ):
            selected_by_index.setdefault(
                index,
                {
                    "path": frame_paths[index],
                    "index": index,
                    "reason": "suspicious_temporal_window",
                    "windowCenterFrame": frame_paths[center_index].name,
                    "windowOffsetFrames": index - center_index,
                    "sourceComparison": {
                        "fromFrame": comparison.get("fromFrame"),
                        "toFrame": comparison.get("toFrame"),
                        "riskSignals": comparison.get("riskSignals", []),
                        "instabilityScore": comparison.get("instabilityScore"),
                    },
                },
            )
            if len(selected_by_index) >= limit:
                return _ordered_selected(selected_by_index)

    fallback_limit = min(limit, max(0, MAX_VISUAL_EVENT_FALLBACK_FRAMES))
    for index in _evenly_spaced_indexes(len(frame_paths), fallback_limit):
        selected_by_index.setdefault(
            index,
            {
                "path": frame_paths[index],
                "index": index,
                "reason": "even_sample_fallback",
                "windowCenterFrame": None,
                "windowOffsetFrames": None,
                "sourceComparison": None,
            },
        )
        if len(selected_by_index) >= limit:
            break

    return _ordered_selected(selected_by_index)


def _window_indexes(*, center_index: int, frame_count: int, radius: int) -> list[int]:
    start = max(0, center_index - radius)
    end = min(frame_count - 1, center_index + radius)
    return list(range(start, end + 1))


def _evenly_spaced_indexes(count: int, limit: int) -> list[int]:
    if count <= 0 or limit <= 0:
        return []
    if count <= limit:
        return list(range(count))
    if limit <= 1:
        return [0]

    last_index = count - 1
    return sorted(
        {
            round((last_index * index) / (limit - 1))
            for index in range(limit)
        }
    )


def _ordered_selected(selected_by_index: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    return [selected_by_index[index] for index in sorted(selected_by_index)]


def _timestamp_for_index(index: int) -> float:
    return round(index / max(FRAME_SAMPLE_RATE, 0.001), 3)


def _summarize(frames: list[dict[str, Any]]) -> dict[str, Any]:
    destructive_events = []
    synthetic_likelihoods = []
    synthetic_signals = set()
    authenticity_scores = []
    authenticity_risk_signals = set()
    authenticity_realism_signals = set()
    authenticity_rationales = []
    selection_reasons = {}

    for frame in frames:
        reason = frame.get("selectionReason") or "unknown"
        selection_reasons[reason] = selection_reasons.get(reason, 0) + 1

        indicators = frame.get("vision", {}).get("indicators", {})
        synthetic = indicators.get("synthetic") or {}
        ai_likelihood = synthetic.get("aiLikelihood")
        if ai_likelihood in {"low", "medium", "high"}:
            synthetic_likelihoods.append(ai_likelihood)
        for signal in synthetic.get("signals") or []:
            synthetic_signals.add(signal)

        authenticity = frame.get("authenticity") or {}
        risk = authenticity.get("authenticityRisk")
        if isinstance(risk, (int, float)):
            authenticity_scores.append(max(0.0, min(1.0, float(risk))))
        if authenticity.get("riskLevel") == "high":
            authenticity_scores.append(0.85)
        elif authenticity.get("riskLevel") == "medium":
            authenticity_scores.append(0.55)
        risk_signals = authenticity.get("riskSignals") or []
        if not risk_signals:
            risk_signals = authenticity.get("signals") or []
        for signal in risk_signals:
            authenticity_risk_signals.add(str(signal))
        for signal in authenticity.get("realismSignals") or []:
            authenticity_realism_signals.add(str(signal))
        rationale = authenticity.get("rationale")
        if rationale and len(authenticity_rationales) < 4:
            authenticity_rationales.append(str(rationale)[:240])

        destructive_event = indicators.get("destructiveEvent") or {}
        event_type = destructive_event.get("type")
        if event_type and event_type not in {"none", "unknown"}:
            destructive_events.append(
                {
                    "frame": frame.get("frame"),
                    "timestamp": frame.get("timestamp"),
                    "type": event_type,
                    "confidence": destructive_event.get("confidence") or "low",
                }
            )

    return {
        "destructiveEventFrameCount": len(destructive_events),
        "destructiveEvents": destructive_events[:12],
        "highestSyntheticLikelihood": _highest_likelihood(synthetic_likelihoods),
        "syntheticSignals": sorted(synthetic_signals),
        "authenticityRiskScore": round(max(authenticity_scores), 4)
        if authenticity_scores
        else None,
        "authenticityRiskSignals": sorted(authenticity_risk_signals)[:12],
        "authenticityRealismSignals": sorted(authenticity_realism_signals)[:12],
        "authenticitySignals": sorted(authenticity_risk_signals)[:12],
        "authenticityRationales": authenticity_rationales,
        "selectionReasons": selection_reasons,
    }


def _highest_likelihood(values: list[str]) -> str:
    order = {"low": 1, "medium": 2, "high": 3}
    if not values:
        return "unknown"
    return max(values, key=lambda value: order.get(value, 0))
