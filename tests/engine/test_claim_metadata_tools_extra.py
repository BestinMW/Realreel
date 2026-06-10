import builtins
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from pipeline import claim_analysis, metadataCollector, ocr, thumbnail, tools, vision


class FakeResponse:
    def __init__(self, status_code=0, stdout="", stderr="", payload=None, text="ok"):
        self.returncode = status_code
        self.status_code = status_code
        self.stdout = stdout
        self.stderr = stderr
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def test_metadata_collector_ffprobe_success_and_errors(monkeypatch, tmp_path):
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    monkeypatch.setattr(metadataCollector, "get_ffprobe_command", lambda: ["ffprobe"])

    monkeypatch.setattr(
        metadataCollector.subprocess,
        "run",
        lambda *args, **kwargs: FakeResponse(
            status_code=0,
            stdout=json.dumps({"format": {"duration": "10"}, "streams": []}),
        ),
    )
    assert metadataCollector.get_video_metadata(video_path)["format"]["duration"] == "10"

    monkeypatch.setattr(
        metadataCollector.subprocess,
        "run",
        lambda *args, **kwargs: FakeResponse(status_code=1, stderr="bad probe"),
    )
    with pytest.raises(RuntimeError, match="bad probe"):
        metadataCollector.get_video_metadata(video_path)

    monkeypatch.setattr(
        metadataCollector.subprocess,
        "run",
        lambda *args, **kwargs: FakeResponse(status_code=0, stdout="{bad json"),
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        metadataCollector.get_video_metadata(video_path)

    with pytest.raises(FileNotFoundError):
        metadataCollector.get_video_metadata(tmp_path / "missing.mp4")


def test_metadata_collector_exiftool_and_platform(monkeypatch, tmp_path):
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"video")
    monkeypatch.setattr(metadataCollector, "extract_video_info", lambda url: {"id": "abc"})
    assert metadataCollector.get_platform_metadata("https://example.com") == {"id": "abc"}

    monkeypatch.setattr(metadataCollector, "resolve_exiftool_path", lambda: None)
    with pytest.raises(FileNotFoundError, match="exiftool not found"):
        metadataCollector.get_embedded_metadata(video_path)

    monkeypatch.setattr(metadataCollector, "resolve_exiftool_path", lambda: "exiftool")
    monkeypatch.setattr(
        metadataCollector.subprocess,
        "run",
        lambda *args, **kwargs: FakeResponse(status_code=0, stdout=json.dumps([{"Make": "Camera"}])),
    )
    assert metadataCollector.get_embedded_metadata(video_path) == [{"Make": "Camera"}]

    monkeypatch.setattr(
        metadataCollector.subprocess,
        "run",
        lambda *args, **kwargs: FakeResponse(status_code=1, stderr="exif failed"),
    )
    with pytest.raises(RuntimeError, match="exif failed"):
        metadataCollector.get_embedded_metadata(video_path)

    monkeypatch.setattr(
        metadataCollector.subprocess,
        "run",
        lambda *args, **kwargs: FakeResponse(status_code=0, stdout=json.dumps({"unexpected": True})),
    )
    with pytest.raises(RuntimeError, match="unexpected JSON shape"):
        metadataCollector.get_embedded_metadata(video_path)


def test_claim_analysis_disabled_missing_key_and_api_paths(monkeypatch):
    monkeypatch.setattr(claim_analysis, "CLAIM_ANALYSIS_ENABLED", False)
    disabled = claim_analysis.analyze_claim(transcript={}, keyframe_analysis={})
    assert disabled["ok"] is False
    assert "disabled" in disabled["error"]

    monkeypatch.setattr(claim_analysis, "CLAIM_ANALYSIS_ENABLED", True)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    missing_key = claim_analysis.analyze_claim(transcript={}, keyframe_analysis={})
    assert "OPENAI_API_KEY" in missing_key["error"]

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(
        claim_analysis.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(status_code=500, text="server error"),
        raising=False,
    )
    failed = claim_analysis.analyze_claim(transcript={"text": "claim"}, keyframe_analysis={})
    assert "server error" in failed["error"]

    def timeout(*args, **kwargs):
        raise claim_analysis.httpx.TimeoutException()

    monkeypatch.setattr(claim_analysis.httpx, "post", timeout, raising=False)
    timed_out = claim_analysis.analyze_claim(transcript={"text": "claim"}, keyframe_analysis={})
    assert "timed out" in timed_out["error"]


def test_claim_analysis_success_and_unparseable_response(monkeypatch):
    monkeypatch.setattr(claim_analysis, "CLAIM_ANALYSIS_ENABLED", True)
    monkeypatch.setenv("OPENAI_API_KEY", "key")
    payload = {
        "output_text": json.dumps(
            {
                "claim": "The video shows an explosion.",
                "claimType": "event",
                "verdict": "unverified",
                "confidence": 0.6,
                "misleadingProbability": 0.2,
                "depictedEvent": "explosion",
                "summary": "The event is not verified.",
                "evidence": [{"sourceTitle": "Source", "url": "https://source.test", "supports": "context"}],
                "recommendedAction": "needs_more_evidence",
            }
        ),
        "sources": [{"title": "Search source", "url": "https://search.test"}],
    }
    monkeypatch.setattr(
        claim_analysis.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(status_code=200, payload=payload),
        raising=False,
    )
    keyframes = {
        "frames": [
            {
                "vision": {
                    "indicators": {
                        "sceneDescription": "A large explosion near a building",
                        "synthetic": {"aiLikelihood": "high", "signals": ["impossible_physics"]},
                        "destructiveEvent": {"type": "explosion", "confidence": "high"},
                    }
                }
            }
        ]
    }
    result = claim_analysis.analyze_claim(
        transcript={"text": "This shows an explosion."},
        keyframe_analysis=keyframes,
        temporal_analysis={"summary": {"aiVisualRiskScore": 0.5, "riskSignals": ["large_change"]}},
    )
    assert result["ok"] is True
    assert result["visualAuthenticityRisk"] >= 0.72
    assert result["recommendedAction"] == "flag_for_review"
    assert result["evidence"][0]["url"] == "https://source.test"
    assert {source["url"] for source in result["sources"]} >= {"https://search.test"}

    monkeypatch.setattr(
        claim_analysis.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(status_code=200, payload={"output_text": "not-json"}),
        raising=False,
    )
    unparseable = claim_analysis.analyze_claim(transcript={"text": "claim"}, keyframe_analysis={})
    assert unparseable["ok"] is False
    assert unparseable["rawResponseText"] == "not-json"


def test_claim_analysis_helper_branches():
    payload = {
        "output": [
            {"content": [{"type": "text", "text": '{"claim":"x"}', "annotations": [{"title": "Ann", "url": "https://ann.test"}]}]},
            {"action": {"sources": [{"title": "Act", "url": "https://act.test"}]}},
        ]
    }
    assert claim_analysis._extract_response_text(payload) == '{"claim":"x"}'
    assert claim_analysis._parse_json_response("prefix {\"claim\":\"x\"} suffix") == {"claim": "x"}
    assert claim_analysis._parse_json_response("[1,2]") is None
    assert claim_analysis._estimate_misleading_probability(verdict="false", confidence=0.5) == 0.725
    assert claim_analysis._estimate_misleading_probability(verdict="bogus", confidence=None) is None
    assert claim_analysis._merge_visual_risk_into_misleading_probability(
        misleading_probability=None,
        visual_authenticity_risk=None,
        verdict="true",
        depicted_event=None,
    ) is None
    assert claim_analysis._normalize_probability(float("nan")) is None
    assert claim_analysis._most_common(["fire", "smoke", "fire"]) == "fire"
    assert claim_analysis._specific_event_details("Explosion in Dallas on January 2, 2025 with 3 dead")
    assert claim_analysis._apply_misleading_probability_floor(
        probability=0.1,
        verdict="false",
        claim_type="satire_or_parody",
    ) == 0.35

    sources = claim_analysis._extract_sources(
        payload,
        [{"sourceTitle": "Existing", "url": "https://ann.test", "supports": "context"}],
    )
    assert [source["url"] for source in sources] == ["https://ann.test", "https://act.test"]


def test_claim_visual_fallback_and_grounding_helpers():
    keyframes = {
        "frames": [
            {
                "vision": {
                    "error": "model failed",
                    "indicators": {
                        "sceneDescription": "A building fire with emergency responders",
                        "notableObjects": ["building"],
                        "notableActions": ["smoke rising"],
                        "visibleText": [{"text": "LOCAL NEWS"}],
                        "destructiveEvent": {"type": "fire"},
                    },
                }
            }
        ]
    }
    normalized = {
        "claim": "no clear claim",
        "claimType": "none",
        "verdict": "no_clear_claim",
        "confidence": None,
        "visualAuthenticityRisk": 0.5,
        "visualAuthenticityRationale": "medium risk",
        "misleadingProbability": 0.1,
        "misleadingProbabilityRationale": "",
        "depictedEvent": "fire",
        "recommendedAction": "needs_more_evidence",
    }
    fallback = claim_analysis._apply_visual_event_fallback(
        normalized,
        keyframe_analysis=keyframes,
        visual_event_analysis=None,
    )
    assert fallback["verdict"] == "unverified"
    assert fallback["recommendedAction"] == "flag_for_review"
    assert "building fire" in fallback["claim"]

    unsupported = claim_analysis._remove_unsupported_web_specifics(
        {
            "claim": "The January 2, 2025 Dallas Factory explosion killed 3 people",
            "summary": "Named incident details",
            "depictedEvent": "explosion",
            "missingContext": [],
            "recommendedAction": "accept",
            "verdict": "true",
        },
        transcript={"text": "A fire is shown"},
        keyframe_analysis=keyframes,
        visual_event_analysis=None,
    )
    assert unsupported["verdict"] == "unverified"
    assert unsupported["recommendedAction"] == "flag_for_review"
    quality = claim_analysis._visual_metadata_quality(
        keyframe_analysis=keyframes,
        visual_event_analysis=None,
    )
    assert quality["meaningfulFrameCount"] == 1
    assert quality["visionErrorCount"] == 1
    assert claim_analysis._frame_has_meaningful_visual_metadata({"sceneDescription": "unknown"}) is False


def test_ocr_happy_path_with_fake_tesseract(monkeypatch, tmp_path):
    frame_path = tmp_path / "frame.jpg"
    Image.new("RGB", (20, 20), "white").save(frame_path)
    fake_tesseract = SimpleNamespace(
        Output=SimpleNamespace(DICT="dict"),
        image_to_data=lambda *args, **kwargs: {
            "text": ["Real", "Reel"],
            "conf": ["90", "80"],
            "block_num": [1, 1],
            "par_num": [1, 1],
            "line_num": [1, 1],
            "left": [1, 20],
            "top": [1, 1],
            "width": [10, 10],
            "height": [5, 5],
        },
    )
    monkeypatch.setattr(ocr, "OCR_ENABLED", True)
    monkeypatch.setattr(ocr, "pytesseract", fake_tesseract)
    monkeypatch.setattr(ocr, "resolve_tesseract_path", lambda: "tesseract")

    result = ocr.analyze_frame(frame_path)

    assert result["ok"] is True
    assert result["text"]["raw"] == "Real Reel"
    assert result["confidence"] == 85.0


def test_tools_additional_resolution_branches(monkeypatch, tmp_path):
    fake_exe = tmp_path / "tool.exe"
    fake_exe.write_text("exe", encoding="utf-8")
    tools.get_ffmpeg_command.cache_clear()
    tools.get_ffprobe_command.cache_clear()
    tools.get_ytdlp_command.cache_clear()

    class FakeImageio:
        @staticmethod
        def get_ffmpeg_exe():
            return str(fake_exe)

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "imageio_ffmpeg":
            return FakeImageio
        if name == "pytesseract":
            return SimpleNamespace(pytesseract=SimpleNamespace(tesseract_cmd=None))
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delenv("FFMPEG_PATH", raising=False)
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    assert tools.get_ffmpeg_command() == [str(fake_exe)]

    tools.get_ffprobe_command.cache_clear()
    ffprobe = tmp_path / ("ffprobe.exe" if tools.os.name == "nt" else "ffprobe")
    ffprobe.write_text("exe", encoding="utf-8")
    monkeypatch.setattr(tools, "get_ffmpeg_command", lambda: [str(fake_exe)])
    assert tools.get_ffprobe_command() == [str(ffprobe)]

    monkeypatch.setenv("EXIFTOOL_PATH", str(fake_exe))
    assert tools.resolve_exiftool_path() == str(fake_exe)
    monkeypatch.setenv("TESSERACT_CMD", str(fake_exe))
    assert tools.configure_tesseract() == str(fake_exe)


def test_vision_error_branches_and_credentials(monkeypatch, tmp_path):
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"jpg")
    monkeypatch.setattr(vision, "VISION_ENABLED", False)
    assert "disabled" in vision.analyze_frame_with_gemini(frame_path)["error"]

    monkeypatch.setattr(vision, "VISION_ENABLED", True)
    monkeypatch.setattr(vision, "VISION_PROVIDER", "google_ai")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert "GEMINI_API_KEY" in vision.analyze_frame_with_gemini(frame_path)["error"]

    monkeypatch.setattr(vision, "VISION_PROVIDER", "vertex_ai")
    monkeypatch.setattr(vision, "VERTEX_AI_PROJECT_ID", "")
    assert "VERTEX_AI_PROJECT_ID" in vision.analyze_frame_with_vertex_ai(frame_path)["error"]
    monkeypatch.setattr(vision, "VISION_PROVIDER", "vertex_ai")
    assert "VERTEX_AI_PROJECT_ID" in vision.analyze_frame_authenticity(frame_path)["error"]

    monkeypatch.setattr(vision, "VERTEX_AI_PROJECT_ID", "project")
    monkeypatch.setattr(vision, "get_vertex_access_token", lambda: (None, "token error"))
    assert vision.analyze_frame_authenticity(frame_path)["error"] == "token error"


def test_vision_http_timeout_error_and_unparseable_branches(monkeypatch, tmp_path):
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"jpg")
    monkeypatch.setattr(vision, "VISION_ENABLED", True)
    monkeypatch.setattr(vision, "VISION_PROVIDER", "google_ai")
    monkeypatch.setenv("GEMINI_API_KEY", "key")

    def timeout(*args, **kwargs):
        raise vision.httpx.TimeoutException()

    monkeypatch.setattr(vision.httpx, "post", timeout, raising=False)
    assert "timed out" in vision.analyze_frame_with_gemini(frame_path)["error"]

    monkeypatch.setattr(
        vision.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(status_code=500, text="bad"),
        raising=False,
    )
    assert "request failed" in vision.analyze_frame_with_gemini(frame_path)["error"]

    monkeypatch.setattr(
        vision.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            status_code=200,
            payload={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not-json"}]}}]},
        ),
        raising=False,
    )
    assert "unparseable" in vision.analyze_frame_with_gemini(frame_path)["error"]

    monkeypatch.setattr(vision, "VISION_PROVIDER", "vertex_ai")
    monkeypatch.setattr(vision, "VERTEX_AI_PROJECT_ID", "project")
    monkeypatch.setattr(vision, "get_vertex_access_token", lambda: ("token", None))
    monkeypatch.setattr(vision.httpx, "post", timeout, raising=False)
    assert "timed out" in vision.analyze_frame_with_vertex_ai(frame_path)["error"]
    assert "timed out" in vision.analyze_frame_authenticity(frame_path)["error"]
    assert "timed out" in vision.analyze_event_window_consistency([{}, {}])["error"]


def test_thumbnail_timeout_exception_and_unparseable_branches(monkeypatch, tmp_path):
    image_path = tmp_path / "thumb.jpg"
    image_path.write_bytes(b"jpg")
    monkeypatch.setenv("GEMINI_API_KEY", "key")

    def timeout(*args, **kwargs):
        raise thumbnail.httpx.TimeoutException()

    monkeypatch.setattr(thumbnail.httpx, "post", timeout, raising=False)
    assert "timed out" in thumbnail._analyze_with_gemini_api(image_path, "prompt")["error"]

    monkeypatch.setattr(
        thumbnail.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            status_code=200,
            payload={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not-json"}]}}]},
        ),
        raising=False,
    )
    assert "unparseable" in thumbnail._analyze_with_gemini_api(image_path, "prompt")["error"]

    monkeypatch.setattr(thumbnail, "VERTEX_AI_PROJECT_ID", "project")
    monkeypatch.setattr("pipeline.vision.get_vertex_access_token", lambda: ("token", None))
    monkeypatch.setattr(thumbnail.httpx, "post", timeout, raising=False)
    assert "timed out" in thumbnail._analyze_with_vertex_ai(image_path, "prompt")["error"]
