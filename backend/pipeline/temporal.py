import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat

from .config import FRAME_SAMPLE_RATE
from .indicators import SCHEMA_VERSION, seconds_to_timestamp


def analyze_temporal_consistency(
    *,
    frame_paths: list[Path],
    keyframe_timestamps: list[float],
    output_path: Path,
) -> dict[str, Any]:
    frames = [
        {
            "frame": frame_path.name,
            "timestampSeconds": _timestamp_for_index(index),
            "timestamp": seconds_to_timestamp(_timestamp_for_index(index)),
        }
        for index, frame_path in enumerate(frame_paths)
    ]
    comparisons = []

    previous_signature = None
    previous_frame = None
    for frame_path, frame in zip(frame_paths, frames):
        signature = _frame_signature(frame_path)
        if previous_signature is not None and previous_frame is not None:
            scene_change_nearby = _has_scene_change_between(
                keyframe_timestamps,
                start=previous_frame["timestampSeconds"],
                end=frame["timestampSeconds"],
            )
            diff = _signature_difference(previous_signature, signature)
            comparison = {
                "fromFrame": previous_frame["frame"],
                "toFrame": frame["frame"],
                "fromTimestamp": previous_frame["timestamp"],
                "toTimestamp": frame["timestamp"],
                "meanPixelDifference": diff["meanPixelDifference"],
                "colorShift": diff["colorShift"],
                "textureShift": diff["textureShift"],
                "sceneChangeNearby": scene_change_nearby,
                "riskSignals": _comparison_risk_signals(diff, scene_change_nearby),
            }
            comparison["instabilityScore"] = _comparison_instability_score(comparison)
            comparisons.append(comparison)

        previous_signature = signature
        previous_frame = frame

    summary = _summarize(comparisons, frame_count=len(frames))
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "providerVersions": {
            "temporal": "pillow-frame-diff-v1",
        },
        "frameSamplingRate": FRAME_SAMPLE_RATE,
        "frameCount": len(frames),
        "comparisonCount": len(comparisons),
        "summary": summary,
        "frames": frames,
        "comparisons": comparisons,
    }
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _timestamp_for_index(index: int) -> float:
    return round(index / max(FRAME_SAMPLE_RATE, 0.001), 3)


def _frame_signature(frame_path: Path) -> dict[str, Any]:
    with Image.open(frame_path) as image:
        rgb = image.convert("RGB").resize((160, 90))
        grayscale = rgb.convert("L")
        edges = grayscale.filter(ImageFilter.FIND_EDGES)
        return {
            "grayscale": grayscale.copy(),
            "rgbMean": ImageStat.Stat(rgb).mean,
            "edgeMean": ImageStat.Stat(edges).mean[0] / 255.0,
        }


def _signature_difference(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, float]:
    difference = ImageChops.difference(previous["grayscale"], current["grayscale"])
    mean_pixel_difference = ImageStat.Stat(difference).mean[0] / 255.0
    color_shift = mean(
        abs(a - b) / 255.0 for a, b in zip(previous["rgbMean"], current["rgbMean"])
    )
    texture_shift = abs(previous["edgeMean"] - current["edgeMean"])
    return {
        "meanPixelDifference": round(mean_pixel_difference, 4),
        "colorShift": round(color_shift, 4),
        "textureShift": round(texture_shift, 4),
    }


def _has_scene_change_between(
    keyframe_timestamps: list[float],
    *,
    start: float,
    end: float,
) -> bool:
    low = min(start, end) + 0.05
    high = max(start, end) + 0.05
    return any(low <= timestamp <= high for timestamp in keyframe_timestamps)


def _comparison_risk_signals(diff: dict[str, float], scene_change_nearby: bool) -> list[str]:
    signals = []
    if diff["meanPixelDifference"] >= 0.45 and not scene_change_nearby:
        signals.append("large_visual_change_without_scene_cut")
    if diff["colorShift"] >= 0.25 and not scene_change_nearby:
        signals.append("large_color_shift_without_scene_cut")
    if diff["textureShift"] >= 0.12 and not scene_change_nearby:
        signals.append("texture_instability_without_scene_cut")
    if diff["meanPixelDifference"] >= 0.6:
        signals.append("possible_object_or_scene_disappearance")
    return signals


def _comparison_instability_score(comparison: dict[str, Any]) -> float:
    score = comparison["meanPixelDifference"] * 0.65
    score += comparison["colorShift"] * 0.2
    score += comparison["textureShift"] * 0.15
    if comparison["sceneChangeNearby"]:
        score *= 0.45
    if comparison["riskSignals"]:
        score += min(0.25, len(comparison["riskSignals"]) * 0.08)
    return round(max(0.0, min(1.0, score)), 4)


def _summarize(comparisons: list[dict[str, Any]], *, frame_count: int) -> dict[str, Any]:
    if not comparisons:
        return {
            "temporalInstabilityScore": None,
            "aiVisualRiskScore": None,
            "objectDisappearanceRisk": None,
            "highInstabilityPairCount": 0,
            "sceneChangePairCount": 0,
            "riskSignals": [],
            "notes": "Not enough sampled frames to compare temporal consistency.",
        }

    instability_scores = [item["instabilityScore"] for item in comparisons]
    high_instability = [item for item in comparisons if item["instabilityScore"] >= 0.45]
    suspicious_pairs = [
        item
        for item in comparisons
        if item["riskSignals"] and not item["sceneChangeNearby"]
    ]
    disappearance_pairs = [
        item
        for item in comparisons
        if "possible_object_or_scene_disappearance" in item["riskSignals"]
    ]
    scene_change_count = sum(1 for item in comparisons if item["sceneChangeNearby"])
    risk_signals = sorted(
        {
            signal
            for item in comparisons
            for signal in item["riskSignals"]
        }
    )
    temporal_instability_score = round(mean(instability_scores), 4)
    ai_visual_risk_score = round(
        min(
            1.0,
            temporal_instability_score * 0.55
            + (len(suspicious_pairs) / len(comparisons)) * 0.35
            + (len(disappearance_pairs) / len(comparisons)) * 0.1,
        ),
        4,
    )
    object_disappearance_risk = round(
        min(1.0, len(disappearance_pairs) / max(len(comparisons), 1)),
        4,
    )

    return {
        "temporalInstabilityScore": temporal_instability_score,
        "aiVisualRiskScore": ai_visual_risk_score,
        "objectDisappearanceRisk": object_disappearance_risk,
        "highInstabilityPairCount": len(high_instability),
        "suspiciousPairCount": len(suspicious_pairs),
        "sceneChangePairCount": scene_change_count,
        "riskSignals": risk_signals,
        "notes": _summary_notes(
            frame_count=frame_count,
            suspicious_pair_count=len(suspicious_pairs),
            scene_change_count=scene_change_count,
        ),
    }


def _summary_notes(
    *,
    frame_count: int,
    suspicious_pair_count: int,
    scene_change_count: int,
) -> str:
    if frame_count < 3:
        return "Low confidence because only a few sampled frames were available."
    if suspicious_pair_count:
        return (
            "Some adjacent frames changed sharply without a nearby detected scene cut; "
            "this can indicate unstable generated visuals, edits, or fast motion."
        )
    if scene_change_count:
        return (
            "Most large visual changes align with detected scene changes, which is less "
            "suggestive of AI temporal inconsistency."
        )
    return "No strong temporal instability signals were detected in the sampled frames."

