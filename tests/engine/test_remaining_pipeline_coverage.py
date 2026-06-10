import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest

from pipeline import media, thumbnail, transcribe, vision, visual_events
from storage.services import videos
from storage.vector import search


class FakeResponse:
    def __init__(self, status_code=200, text="ok", payload=None, content=b"bytes"):
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}
        self.content = content

    def json(self):
        return self._payload


def gemini_payload(parsed):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": json.dumps(parsed)}]},
            }
        ]
    }


def test_media_ffmpeg_helpers_and_extractors(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, capture_output=True, text=True, check=False):
        calls.append(command)
        if "-i" in command and any(str(part).endswith("probe.mp4") for part in command):
            return SimpleNamespace(returncode=1, stdout="", stderr="Duration: 00:01:02.50")
        return SimpleNamespace(returncode=0, stdout="", stderr="pts_time:0.5 pts_time:2.25")

    monkeypatch.setattr(media, "get_ffmpeg_command", lambda: ["ffmpeg"])
    monkeypatch.setattr(media.subprocess, "run", fake_run)

    assert media.run_ffmpeg(["-version"], capture_stderr=True) == "pts_time:0.5 pts_time:2.25"
    assert media.probe_duration_seconds(tmp_path / "probe.mp4") == 62.5
    assert media.compute_adaptive_frame_sample_rate(120) > 0

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    frames_dir = tmp_path / "frames"
    keyframes_dir = tmp_path / "keyframes"
    assert media.extract_sampled_frames(source, frames_dir) > 0
    assert media.extract_keyframes(source, keyframes_dir) == [0.5, 2.25]
    media.create_audio_with_lead_in(tmp_path / "audio.wav", tmp_path / "lead.wav")

    visible = frames_dir / "frame.jpg"
    hidden = frames_dir / ".hidden.jpg"
    visible.write_bytes(b"frame")
    hidden.write_bytes(b"hidden")
    assert media.list_image_files(frames_dir) == [visible]
    assert media.list_image_files(tmp_path / "missing") == []
    assert any("frame_%05d.jpg" in str(part) for command in calls for part in command)


def test_media_run_ffmpeg_failure_paths(monkeypatch):
    monkeypatch.setattr(media, "get_ffmpeg_command", lambda: ["missing-ffmpeg"])

    def missing_binary(*args, **kwargs):
        raise FileNotFoundError("missing binary")

    monkeypatch.setattr(media.subprocess, "run", missing_binary)
    with pytest.raises(RuntimeError, match="missing binary"):
        media.run_ffmpeg(["-version"])

    monkeypatch.setattr(
        media.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="bad args"),
    )
    with pytest.raises(RuntimeError, match="bad args"):
        media.run_ffmpeg(["-bad"])


def test_extract_audio_falls_back_to_silence(monkeypatch, tmp_path):
    calls = []
    audio_path = tmp_path / "audio.wav"

    def fake_run_ffmpeg(args, capture_stderr=False):
        calls.append(args)
        if len(calls) == 1:
            raise RuntimeError("no audio stream")
        audio_path.write_bytes(b"silence")
        return ""

    monkeypatch.setattr(media, "run_ffmpeg", fake_run_ffmpeg)
    monkeypatch.setattr(media, "probe_duration_seconds", lambda path: 4.0)

    media.extract_audio(tmp_path / "video.mp4", audio_path)

    assert audio_path.exists()
    assert calls[1][0:2] == ["-f", "lavfi"]


def test_thumbnail_download_and_provider_branches(monkeypatch, tmp_path):
    target = tmp_path / "thumbnail.jpg"
    monkeypatch.setattr(
        thumbnail.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse(status_code=200, content=b"jpg"),
        raising=False,
    )
    assert thumbnail.download_thumbnail(thumbnail_url="https://example.com/t.jpg", output_path=target) == target
    assert target.read_bytes() == b"jpg"

    monkeypatch.setattr(
        thumbnail.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse(status_code=404, content=b""),
        raising=False,
    )
    assert thumbnail.download_thumbnail(thumbnail_url="https://example.com/missing.jpg", output_path=target) is None

    monkeypatch.setattr(thumbnail, "extract_video_info", lambda url: {"thumbnail": "thumb.jpg"})
    assert thumbnail.get_thumbnail_url("https://example.com/video") == "thumb.jpg"
    monkeypatch.setattr(thumbnail, "extract_video_info", lambda url: (_ for _ in ()).throw(RuntimeError("bad")))
    assert thumbnail.get_thumbnail_url("bad") is None


def test_thumbnail_clickbait_api_success_and_failures(monkeypatch, tmp_path):
    image_path = tmp_path / "thumbnail.jpg"
    image_path.write_bytes(b"jpg")
    monkeypatch.setattr(thumbnail, "VISION_ENABLED", False)
    assert "Vision disabled" in thumbnail.analyze_thumbnail_clickbait(
        thumbnail_path=image_path,
        transcript={},
        claim_analysis={},
        keyframe_analysis={},
    )["error"]

    monkeypatch.setattr(thumbnail, "VISION_ENABLED", True)
    monkeypatch.setattr(thumbnail, "VISION_PROVIDER", "google_ai")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert "GEMINI_API_KEY" in thumbnail._analyze_with_gemini_api(image_path, "prompt")["error"]

    monkeypatch.setenv("GEMINI_API_KEY", "key")
    monkeypatch.setattr(
        thumbnail.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            payload=gemini_payload(
                {
                    "clickbaitScore": 0.45,
                    "riskLevel": "medium",
                    "thumbnailSummary": "dramatic frame",
                    "rationale": "partly supported",
                    "mismatches": ["exaggerated"],
                    "supportingSignals": ["same subject"],
                }
            )
        ),
        raising=False,
    )
    result = thumbnail._analyze_with_gemini_api(image_path, "prompt")
    assert result["ok"] is True
    assert result["riskLevel"] == "medium"

    monkeypatch.setattr(
        thumbnail.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(status_code=500, text="server error"),
        raising=False,
    )
    assert "server error" in thumbnail._analyze_with_gemini_api(image_path, "prompt")["error"]


def test_thumbnail_vertex_success_and_token_failures(monkeypatch, tmp_path):
    image_path = tmp_path / "thumbnail.jpg"
    image_path.write_bytes(b"jpg")
    monkeypatch.setattr(thumbnail, "VERTEX_AI_PROJECT_ID", "")
    assert "VERTEX_AI_PROJECT_ID" in thumbnail._analyze_with_vertex_ai(image_path, "prompt")["error"]

    monkeypatch.setattr(thumbnail, "VERTEX_AI_PROJECT_ID", "project")
    monkeypatch.setattr("pipeline.vision.get_vertex_access_token", lambda: (None, "no token"))
    assert thumbnail._analyze_with_vertex_ai(image_path, "prompt")["error"] == "no token"

    monkeypatch.setattr("pipeline.vision.get_vertex_access_token", lambda: ("token", None))
    monkeypatch.setattr(
        thumbnail.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(payload=gemini_payload({"clickbaitScore": 0.1})),
        raising=False,
    )
    assert thumbnail._analyze_with_vertex_ai(image_path, "prompt")["ok"] is True


def test_vision_vertex_authenticity_and_event_window_success(monkeypatch, tmp_path):
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"jpg")
    monkeypatch.setattr(vision, "VISION_ENABLED", True)
    monkeypatch.setattr(vision, "VISION_PROVIDER", "vertex_ai")
    monkeypatch.setattr(vision, "VERTEX_AI_PROJECT_ID", "project")
    monkeypatch.setattr(vision, "get_vertex_access_token", lambda: ("token", None))

    payloads = [
        gemini_payload({"sceneDescription": "street", "notableObjects": ["car"]}),
        gemini_payload(
            {
                "authenticityRisk": 0.4,
                "riskLevel": "medium",
                "rationale": "minor artifacts",
                "riskSignals": ["blur"],
                "realismSignals": ["shadows"],
            }
        ),
        gemini_payload(
            {
                "physicalConsistencyRisk": 0.1,
                "subjectReactionRisk": 0.2,
                "lightingContinuityRisk": 0.3,
                "debrisMotionRisk": 0.4,
                "cameraContinuityRisk": 0.5,
                "overallTemporalAuthenticityRisk": 0.6,
                "rationale": "mostly consistent",
                "riskSignals": ["small jump"],
                "consistencySignals": ["same lighting"],
            }
        ),
    ]

    def fake_post(*args, **kwargs):
        return FakeResponse(payload=payloads.pop(0))

    monkeypatch.setattr(vision.httpx, "post", fake_post, raising=False)

    assert vision.analyze_frame_with_vertex_ai(frame_path)["ok"] is True
    assert vision.analyze_frame_authenticity(frame_path)["authenticityRisk"] == 0.4
    consistency = vision.analyze_event_window_consistency(
        [
            {"frame": "a.jpg", "vision": {"indicators": {"sceneDescription": "a"}}, "authenticity": {}},
            {"frame": "b.jpg", "vision": {"indicators": {"sceneDescription": "b"}}, "authenticity": {}},
        ]
    )
    assert consistency["overallTemporalAuthenticityRisk"] == 0.6


def test_vision_event_window_configuration_failures(monkeypatch):
    monkeypatch.setattr(vision, "VISION_ENABLED", False)
    assert "Vision disabled" in vision.analyze_event_window_consistency([{}, {}])["error"]
    monkeypatch.setattr(vision, "VISION_ENABLED", True)
    monkeypatch.setattr(vision, "VISION_PROVIDER", "google_ai")
    assert "requires VISION_PROVIDER" in vision.analyze_event_window_consistency([{}, {}])["error"]
    monkeypatch.setattr(vision, "VISION_PROVIDER", "vertex_ai")
    monkeypatch.setattr(vision, "VERTEX_AI_PROJECT_ID", "project")
    assert "Not enough frames" in vision.analyze_event_window_consistency([{}])["error"]


def test_visual_events_full_analysis_with_mocked_vision(monkeypatch, tmp_path):
    frame_paths = []
    for index in range(3):
        path = tmp_path / f"frame_{index:05d}.jpg"
        path.write_bytes(b"frame")
        frame_paths.append(path)

    monkeypatch.setattr(
        visual_events,
        "analyze_frame_with_gemini",
        lambda path, ocr_summary=None: {
            "ok": True,
            "indicators": {
                "synthetic": {"aiLikelihood": "high", "signals": ["warped"]},
                "destructiveEvent": {"type": "fire", "confidence": "medium"},
            },
            "error": None,
        },
    )
    monkeypatch.setattr(
        visual_events,
        "analyze_frame_authenticity",
        lambda path: {
            "ok": True,
            "authenticityRisk": 0.7,
            "riskLevel": "high",
            "riskSignals": ["shadow mismatch"],
            "realismSignals": ["camera shake"],
            "rationale": "visible mismatch",
            "error": None,
        },
    )
    monkeypatch.setattr(
        visual_events,
        "analyze_event_window_consistency",
        lambda frames: {"ok": True, "overallTemporalAuthenticityRisk": 0.5},
    )

    result = visual_events.analyze_visual_events(
        frame_paths=frame_paths,
        temporal_analysis={"comparisons": []},
        output_path=tmp_path / "visual-events.json",
        frame_sample_rate=2,
    )

    assert result["frameCount"] > 0
    assert result["summary"]["highestSyntheticLikelihood"] == "high"
    assert result["summary"]["authenticityRiskScore"] == 0.85


def test_transcribe_audio_success_and_failures(monkeypatch, tmp_path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"audio")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        transcribe.transcribe_audio_with_openai(audio_path)

    monkeypatch.setenv("OPENAI_API_KEY", "key")
    monkeypatch.setattr(transcribe, "OPENAI_AUDIO_FILE_LIMIT_BYTES", 1)
    with pytest.raises(RuntimeError, match="larger than OpenAI"):
        transcribe.transcribe_audio_with_openai(audio_path)

    monkeypatch.setattr(transcribe, "OPENAI_AUDIO_FILE_LIMIT_BYTES", 100)

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse(payload={"text": "hello"})

    monkeypatch.setattr(transcribe.httpx, "Client", FakeClient, raising=False)
    assert transcribe.transcribe_audio_with_openai(audio_path) == {"text": "hello"}

    class FailingClient(FakeClient):
        def post(self, *args, **kwargs):
            return FakeResponse(status_code=400, text="bad request")

    monkeypatch.setattr(transcribe.httpx, "Client", FailingClient, raising=False)
    with pytest.raises(RuntimeError, match="bad request"):
        transcribe.transcribe_audio_with_openai(audio_path)


@pytest.mark.anyio
async def test_storage_video_insert_update_and_vector_query(monkeypatch):
    class Existing:
        original_url = "old"

    class FakeScalar:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class FakeSession:
        def __init__(self, existing=None):
            self.existing = existing
            self.added = None
            self.flushed = False
            self.executed = []

        async def execute(self, query, params=None):
            self.executed.append((query, params))
            if params is not None:
                row = SimpleNamespace(
                    _mapping={
                        "id": "video-1",
                        "original_url": "https://example.com/old",
                        "distance": 0.1,
                        "similarity": 0.9,
                    }
                )
                return [row]
            return FakeScalar(self.existing)

        def add(self, value):
            self.added = value

        async def flush(self):
            self.flushed = True

    existing = Existing()
    update_session = FakeSession(existing)
    updated = await videos._insert_or_update_video(
        update_session,
        {"original_url": "https://example.com/video", "title": "New title"},
    )
    assert updated is existing
    assert existing.title == "New title"
    assert update_session.flushed

    class FakeVideo:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(videos, "Video", FakeVideo)
    monkeypatch.setattr(videos, "find_video_by_url", lambda session, url: asyncio.sleep(0, result=None))
    insert_session = FakeSession(None)
    inserted = await videos._insert_or_update_video(
        insert_session,
        {"original_url": "https://example.com/new", "title": "Inserted"},
    )
    assert inserted.kwargs["title"] == "Inserted"
    assert insert_session.added is inserted

    monkeypatch.setattr(search.settings, "embedding_dimension", 3)
    query_session = FakeSession()
    matches = await search.find_similar_videos(
        query_session,
        embedding=[0.1, 0.2, 0.3],
        limit=1,
        exclude_original_url="https://example.com/current",
    )
    assert matches[0]["similarity"] == 0.9
    assert query_session.executed[0][1]["embedding"] == "[0.1,0.2,0.3]"
