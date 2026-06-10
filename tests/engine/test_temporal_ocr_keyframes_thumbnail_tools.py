from pathlib import Path
import builtins

import pytest
from PIL import Image

from pipeline import keyframes, ocr, temporal, thumbnail, tools


def test_temporal_consistency_handles_not_enough_frames(tmp_path):
    output_path = tmp_path / "temporal.json"

    result = temporal.analyze_temporal_consistency(
        frame_paths=[],
        keyframe_timestamps=[],
        output_path=output_path,
        frame_sample_rate=2,
    )

    assert result["frameCount"] == 0
    assert result["comparisonCount"] == 0
    assert result["summary"]["temporalInstabilityScore"] is None
    assert output_path.exists()


def test_temporal_consistency_flags_large_change_without_scene_cut(tmp_path):
    first = tmp_path / "frame_00000.jpg"
    second = tmp_path / "frame_00001.jpg"
    Image.new("RGB", (20, 20), "black").save(first)
    Image.new("RGB", (20, 20), "white").save(second)

    result = temporal.analyze_temporal_consistency(
        frame_paths=[first, second],
        keyframe_timestamps=[],
        output_path=tmp_path / "temporal.json",
        frame_sample_rate=1,
    )

    comparison = result["comparisons"][0]
    assert comparison["meanPixelDifference"] == 1.0
    assert "large_visual_change_without_scene_cut" in comparison["riskSignals"]
    assert "possible_object_or_scene_disappearance" in comparison["riskSignals"]
    assert result["summary"]["objectDisappearanceRisk"] == 1.0


def test_temporal_scene_change_reduces_instability():
    comparison = {
        "meanPixelDifference": 0.8,
        "colorShift": 0.5,
        "textureShift": 0.2,
        "sceneChangeNearby": True,
        "riskSignals": [],
    }

    assert temporal._comparison_instability_score(comparison) < 0.4
    assert temporal._has_scene_change_between([1.0], start=0.0, end=1.0)


def test_ocr_empty_result_and_line_collection():
    empty = ocr.empty_ocr_result("disabled")

    assert empty["ok"] is False
    assert empty["text"]["wordCount"] == 0
    assert empty["error"] == "disabled"

    data = {
        "text": ["Real", "Reel", "", "low"],
        "conf": ["90", "80", "95", "1"],
        "block_num": [1, 1, 1, 1],
        "par_num": [1, 1, 1, 1],
        "line_num": [1, 1, 2, 2],
        "left": [10, 45, 0, 5],
        "top": [20, 20, 40, 40],
        "width": [30, 30, 5, 10],
        "height": [10, 10, 5, 5],
    }
    lines = ocr._collect_lines(data)

    assert len(lines) == 1
    assert lines[0]["text"] == "Real Reel"
    assert ocr._build_raw_text(lines) == "Real Reel"


def test_ocr_analyze_frame_reports_disabled(monkeypatch, tmp_path):
    frame_path = tmp_path / "frame.jpg"
    Image.new("RGB", (10, 10), "white").save(frame_path)
    monkeypatch.setattr(ocr, "OCR_ENABLED", False)

    result = ocr.analyze_frame(frame_path)

    assert result["ok"] is False
    assert "OCR disabled" in result["error"]


def test_keyframe_stream_combines_ocr_vision_and_progress(monkeypatch, tmp_path):
    frame_path = tmp_path / "frame_00001.jpg"
    frame_path.write_text("placeholder", encoding="utf-8")
    output_path = tmp_path / "keyframes.json"

    monkeypatch.setattr(
        keyframes,
        "analyze_frame_ocr",
        lambda path: {
            "ok": True,
            "text": {"raw": "Breaking", "lines": [], "wordCount": 1},
            "indicators": {"visibleText": ["Breaking"]},
            "confidence": 91.0,
            "error": None,
        },
    )
    monkeypatch.setattr(
        keyframes,
        "analyze_frame_with_gemini",
        lambda path, ocr_summary: {
            "ok": True,
            "indicators": {"sceneDescription": "A street scene", "visibleText": ["Breaking"]},
            "error": None,
        },
    )

    events = list(
        keyframes.analyze_keyframes_stream(
            keyframe_paths=[frame_path],
            keyframe_timestamps=[2.5],
            output_path=output_path,
        )
    )

    assert events[0]["kind"] == "progress"
    assert events[-1]["kind"] == "result"
    result = events[-1]["payload"]
    assert result["frameCount"] == 1
    assert result["frames"][0]["timestampSeconds"] == 2.5
    assert output_path.exists()


def test_keyframe_analyze_raises_when_no_result(monkeypatch, tmp_path):
    monkeypatch.setattr(keyframes, "analyze_keyframes_stream", lambda **kwargs: iter([]))

    with pytest.raises(RuntimeError, match="did not produce a result"):
        keyframes.analyze_keyframes(
            keyframe_paths=[],
            keyframe_timestamps=[],
            output_path=tmp_path / "out.json",
        )


def test_thumbnail_url_selection_and_fallback_copy(tmp_path):
    info = {
        "thumbnail": "https://example.com/default.jpg",
        "thumbnails": [
            {"url": "https://example.com/small.jpg"},
            {"url": "https://example.com/large.jpg"},
        ],
    }

    assert thumbnail.get_thumbnail_url_from_info(info) == "https://example.com/large.jpg"
    assert thumbnail.get_thumbnail_url_from_info({"thumbnail": "fallback.jpg"}) == "fallback.jpg"
    assert thumbnail.get_thumbnail_url_from_info(None) is None

    source = tmp_path / "frame.jpg"
    target = tmp_path / "thumbs" / "thumbnail.jpg"
    source.write_bytes(b"jpg")

    assert thumbnail.create_thumbnail_fallback(
        keyframe_paths=[source],
        output_path=target,
    ) == target
    assert target.read_bytes() == b"jpg"
    assert thumbnail.create_thumbnail_fallback(keyframe_paths=[], output_path=target) is None


def test_thumbnail_context_and_model_response_normalization(monkeypatch):
    context = thumbnail._build_context(
        transcript={"text": "A short transcript" * 500},
        claim_analysis={"claim": "claim", "verdict": "verified", "summary": "summary"},
        keyframe_analysis={
            "frames": [
                {
                    "timestamp": "00:01",
                    "vision": {
                        "indicators": {
                            "sceneDescription": "street",
                            "visibleText": ["SALE"],
                            "notableObjects": ["car"],
                            "notableActions": ["driving"],
                            "destructiveEvent": None,
                        }
                    },
                }
            ]
        },
        visual_event_analysis=None,
    )
    assert "transcriptPreview" in context
    assert len(context) <= 12000

    monkeypatch.setattr(thumbnail, "extract_gemini_text", lambda payload: ("{}", None))
    monkeypatch.setattr(
        thumbnail,
        "parse_json_response",
        lambda text: {
            "clickbaitScore": 2,
            "riskLevel": "not-a-level",
            "thumbnailSummary": "summary",
            "rationale": "reason",
            "mismatches": [" mismatch ", ""],
            "supportingSignals": ["match"],
        },
    )

    result = thumbnail._normalize_model_response({"fake": "payload"})

    assert result["ok"] is True
    assert result["clickbaitScore"] == 1.0
    assert result["riskLevel"] == "high"
    assert result["mismatches"] == ["mismatch"]
    assert thumbnail._string_list("not-list", limit=2) == []


def test_thumbnail_analysis_returns_empty_result_when_missing_file():
    result = thumbnail.analyze_thumbnail_clickbait(
        thumbnail_path=None,
        transcript={},
        claim_analysis={},
        keyframe_analysis={},
    )

    assert result["ok"] is False
    assert result["riskLevel"] == "unknown"
    assert "No thumbnail" in result["error"]


def test_tools_resolve_from_environment(monkeypatch, tmp_path):
    fake_exe = tmp_path / "tool.exe"
    fake_exe.write_text("exe", encoding="utf-8")

    tools.get_ffmpeg_command.cache_clear()
    tools.get_ffprobe_command.cache_clear()
    tools.get_ytdlp_command.cache_clear()

    monkeypatch.setenv("FFMPEG_PATH", str(fake_exe))
    monkeypatch.setenv("FFPROBE_PATH", str(fake_exe))
    monkeypatch.setenv("YTDLP_PATH", str(fake_exe))
    monkeypatch.setenv("TESSERACT_CMD", str(fake_exe))

    assert tools.get_ffmpeg_command() == [str(fake_exe)]
    assert tools.get_ffmpeg_location_for_ytdlp() == str(fake_exe)
    assert tools.get_ffprobe_command() == [str(fake_exe)]
    assert tools.get_ytdlp_command() == [str(fake_exe)]
    assert tools.resolve_tesseract_path() == str(fake_exe)


def test_tools_raise_when_binaries_are_missing(monkeypatch):
    tools.get_ffmpeg_command.cache_clear()
    tools.get_ffprobe_command.cache_clear()
    tools.get_ytdlp_command.cache_clear()

    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.delenv("FFPROBE_PATH", raising=False)
    monkeypatch.delenv("YTDLP_PATH", raising=False)
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    monkeypatch.setattr(tools, "get_venv_python", lambda: None)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yt_dlp":
            raise ImportError("yt-dlp intentionally hidden")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(FileNotFoundError, match="ffmpeg not found|ffprobe not found"):
        tools.get_ffprobe_command()

    with pytest.raises(FileNotFoundError, match="yt-dlp not found"):
        tools.get_ytdlp_command()
