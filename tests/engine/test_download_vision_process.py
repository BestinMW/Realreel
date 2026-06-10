import json
import sys
import types
from pathlib import Path

import pytest

from pipeline import download, process, vision


class FakeYoutubeDL:
    def __init__(self, opts, *, extracted=None, sanitized=None):
        self.opts = opts
        self.extracted = extracted if extracted is not None else {"id": "abc"}
        self.sanitized = sanitized

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=False):
        self.url = url
        self.download = download
        return self.extracted

    def sanitize_info(self, info, download=False):
        if self.sanitized is not None:
            return self.sanitized
        return info


def install_fake_ytdlp(monkeypatch, factory):
    fake_module = types.SimpleNamespace(YoutubeDL=factory)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)


def test_extract_video_info_uses_first_playlist_entry(monkeypatch):
    install_fake_ytdlp(
        monkeypatch,
        lambda opts: FakeYoutubeDL(
            opts,
            extracted={"_type": "playlist", "entries": [None, {"id": "first"}]},
        ),
    )
    monkeypatch.setattr(download, "get_ffmpeg_location_for_ytdlp", lambda: "ffmpeg")

    info = download.extract_video_info(" https://example.com/playlist ")

    assert info == {"id": "first"}


def test_extract_video_info_rejects_empty_url():
    with pytest.raises(ValueError, match="URL is required"):
        download.extract_video_info("   ")


def test_find_downloaded_video_prefers_merged_file(tmp_path):
    fragment = tmp_path / "source.f248.mp4"
    merged = tmp_path / "source.mp4"
    fragment.write_bytes(b"fragment")
    merged.write_bytes(b"merged")

    assert download.find_downloaded_video(tmp_path) == merged


def test_download_video_with_info_invokes_ytdlp_and_returns_file(monkeypatch, tmp_path):
    downloaded = tmp_path / "source.mp4"

    class DownloadingYoutubeDL(FakeYoutubeDL):
        def extract_info(self, url, download=False):
            downloaded.write_bytes(b"video")
            return {"id": "downloaded", "title": "Downloaded"}

    install_fake_ytdlp(monkeypatch, lambda opts: DownloadingYoutubeDL(opts))
    monkeypatch.setattr(download, "get_ffmpeg_location_for_ytdlp", lambda: "ffmpeg")

    video_path, info = download.download_video_with_info(
        "https://example.com/video",
        tmp_path,
    )

    assert video_path == downloaded
    assert info["id"] == "downloaded"


def test_vision_parse_json_response_handles_fences_and_repairs():
    assert vision.parse_json_response('```json\n{"medium": true,}\n```') == {
        "medium": True
    }
    assert vision.parse_json_response("prefix {\"medium\": false} suffix") == {
        "medium": False
    }
    assert vision.parse_json_response("") is None


def test_extract_gemini_text_handles_blocked_and_successful_payloads():
    blocked = {"promptFeedback": {"blockReason": "SAFETY"}}
    success = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": "hello"}, {"text": " world"}]},
            }
        ]
    }

    assert vision.extract_gemini_text(blocked)[1] == "Gemini blocked the request: SAFETY"
    assert vision.extract_gemini_text(success) == ("hello world", None)
    assert vision.extract_gemini_text({"candidates": []})[1] == "Gemini returned no candidates."


def test_vision_normalizers_clamp_and_trim_values():
    authenticity = vision.normalize_authenticity_result(
        {
            "authenticityRisk": 2.5,
            "riskLevel": "high",
            "rationale": " reason ",
            "riskSignals": [" warped "],
            "realismSignals": ["shadow"],
            "signals": ["legacy"],
        }
    )
    consistency = vision.normalize_event_consistency_result(
        {
            "physicalConsistencyRisk": -1,
            "subjectReactionRisk": 0.25,
            "lightingContinuityRisk": 9,
            "debrisMotionRisk": "bad",
            "cameraContinuityRisk": 0.5,
            "overallTemporalAuthenticityRisk": 0.75,
            "rationale": " ok ",
            "riskSignals": ["jump"],
            "consistencySignals": ["shadow"],
        }
    )

    assert authenticity["authenticityRisk"] == 1.0
    assert authenticity["riskSignals"] == ["warped"]
    assert consistency["physicalConsistencyRisk"] == 0.0
    assert consistency["lightingContinuityRisk"] == 1.0
    assert consistency["debrisMotionRisk"] is None


def test_analyze_frame_with_gemini_retries_without_schema(monkeypatch, tmp_path):
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"jpg")
    calls = []

    class Response:
        def __init__(self, status_code, text, payload):
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def json(self):
            return self._payload

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return Response(400, "responseSchema not supported", {})
        return Response(
            200,
            "ok",
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "sceneDescription": "A city street",
                                            "notableObjects": ["car"],
                                        }
                                    )
                                }
                            ]
                        },
                    }
                ]
            },
        )

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(vision, "VISION_ENABLED", True)
    monkeypatch.setattr(vision, "VISION_PROVIDER", "google_ai")
    monkeypatch.setattr(vision.httpx, "post", fake_post, raising=False)

    result = vision.analyze_frame_with_gemini(frame_path, ocr_summary="text")

    assert result["ok"] is True
    assert len(calls) == 2
    assert "responseSchema" not in calls[1]["generationConfig"]
    assert result["indicators"]["sceneDescription"] == "A city street"


def test_analyze_frame_authenticity_requires_vertex_provider(monkeypatch, tmp_path):
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"jpg")
    monkeypatch.setattr(vision, "VISION_ENABLED", True)
    monkeypatch.setattr(vision, "VISION_PROVIDER", "google_ai")

    result = vision.analyze_frame_authenticity(frame_path)

    assert result["ok"] is False
    assert "requires VISION_PROVIDER=vertex_ai" in result["error"]


def test_process_youtube_video_fast_mode_success(monkeypatch, tmp_path):
    monkeypatch.setattr(process, "UPLOADS_ROOT", tmp_path)
    monkeypatch.setattr(process.time, "time", lambda: 123.456)
    monkeypatch.setattr(process, "UPLOAD_RAW_VIDEO", True)

    def fake_download(url, job_dir):
        video_path = job_dir / "source.mp4"
        video_path.write_bytes(b"video")
        return video_path, {"thumbnail": None, "uploader_id": "uploader"}

    def fake_extract_audio(video_path, audio_path):
        audio_path.write_bytes(b"audio")

    def fake_create_audio_with_lead_in(audio_path, output_path):
        output_path.write_bytes(b"audio lead")

    def fake_extract_sampled_frames(video_path, frames_dir):
        (frames_dir / "frame_00000.jpg").write_bytes(b"frame")
        return 1

    def fake_extract_keyframes(video_path, keyframes_dir):
        (keyframes_dir / "keyframe_00000.jpg").write_bytes(b"keyframe")
        return [0.0]

    def fake_list_image_files(directory):
        return sorted(directory.glob("*.jpg"))

    def fake_temporal(**kwargs):
        kwargs["output_path"].write_text("{}", encoding="utf-8")
        return {
            "summary": {
                "temporalInstabilityScore": 0.1,
                "aiVisualRiskScore": 0.2,
                "objectDisappearanceRisk": 0.0,
                "riskSignals": [],
            }
        }

    def fake_keyframes_stream(**kwargs):
        kwargs["output_path"].write_text("{}", encoding="utf-8")
        yield {"kind": "progress", "payload": {"index": 1, "total": 1}}
        yield {
            "kind": "result",
            "payload": {
                "frames": [
                    {
                        "ocr": {"indicators": {"hasText": True}},
                        "vision": {
                            "indicators": {
                                "visibleText": ["TEXT"],
                                "sceneDescription": "street",
                                "contextSignals": ["signal"],
                                "synthetic": {"signals": []},
                            },
                            "error": None,
                        },
                        "hints": ["hint"],
                    }
                ]
            },
        }

    monkeypatch.setattr(process, "download_video_with_info", fake_download)
    monkeypatch.setattr(process, "compute_file_sha256", lambda path: "a" * 64)
    monkeypatch.setattr(process, "get_thumbnail_url_from_info", lambda info: None)
    monkeypatch.setattr(process, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(process, "create_audio_with_lead_in", fake_create_audio_with_lead_in)
    monkeypatch.setattr(process, "extract_sampled_frames", fake_extract_sampled_frames)
    monkeypatch.setattr(process, "extract_keyframes", fake_extract_keyframes)
    monkeypatch.setattr(process, "list_image_files", fake_list_image_files)
    monkeypatch.setattr(process, "download_thumbnail", lambda **kwargs: None)
    monkeypatch.setattr(process, "create_thumbnail_fallback", lambda **kwargs: None)
    monkeypatch.setattr(process, "analyze_temporal_consistency", fake_temporal)
    monkeypatch.setattr(
        process,
        "transcribe_audio_with_openai",
        lambda path: {"text": "This video makes a claim."},
    )
    monkeypatch.setattr(process, "analyze_keyframes_stream", fake_keyframes_stream)
    monkeypatch.setattr(
        process,
        "assess_repost_history",
        lambda *args, **kwargs: ({}, None, {"isRepost": False, "matches": []}, None),
    )
    monkeypatch.setattr(
        process,
        "analyze_claim",
        lambda **kwargs: {
            "ok": True,
            "claim": "claim",
            "verdict": "supported",
            "confidence": 0.8,
            "summary": "summary",
            "evidence": [1],
            "misleadingProbability": 0.1,
            "visualAuthenticityRisk": 0.2,
        },
    )
    monkeypatch.setattr(process, "ensure_storage_buckets", lambda buckets: None)
    monkeypatch.setattr(process, "upload_to_supabase_storage", lambda **kwargs: kwargs["storage_path"])
    monkeypatch.setattr(
        process,
        "persist_analysis_record",
        lambda **kwargs: {"ok": True, "videoId": "video-1", "error": None},
    )

    events = list(
        process.process_youtube_video(
            "https://www.youtube.com/watch?v=abc123",
            fast_processing_mode=True,
        )
    )

    assert events[-1]["type"] == "complete"
    result = events[-1]["result"]
    assert result["success"] is True
    assert result["rawVideoPath"] is None
    assert result["rawVideoUploadSkippedReason"] == "FAST_PROCESSING_MODE=true skips raw MP4 upload."
    assert result["databaseSaveOk"] is True
    assert result["frameCount"] == 1
    assert result["crossModalHintCount"] == 1


def test_process_youtube_video_nonfast_raw_upload_too_large_continues(monkeypatch, tmp_path):
    monkeypatch.setattr(process, "UPLOADS_ROOT", tmp_path)
    monkeypatch.setattr(process.time, "time", lambda: 999.0)
    monkeypatch.setattr(process, "UPLOAD_RAW_VIDEO", True)

    def fake_download(url, job_dir):
        video_path = job_dir / "source.mp4"
        video_path.write_bytes(b"video")
        return video_path, {"thumbnail": "https://example.com/thumb.jpg"}

    def write_file(path, content):
        path.write_bytes(content)

    monkeypatch.setattr(process, "download_video_with_info", fake_download)
    monkeypatch.setattr(process, "compute_file_sha256", lambda path: "b" * 64)
    monkeypatch.setattr(process, "get_thumbnail_url_from_info", lambda info: info.get("thumbnail"))
    monkeypatch.setattr(process, "extract_audio", lambda video, audio: write_file(audio, b"audio"))
    monkeypatch.setattr(process, "create_audio_with_lead_in", lambda audio, output: write_file(output, b"lead-audio"))
    monkeypatch.setattr(
        process,
        "extract_sampled_frames",
        lambda video, frames_dir: (write_file(frames_dir / "frame_00000.jpg", b"frame") or 1),
    )
    monkeypatch.setattr(
        process,
        "extract_keyframes",
        lambda video, keyframes_dir: (write_file(keyframes_dir / "keyframe_00000.jpg", b"keyframe") or [0.0]),
    )
    monkeypatch.setattr(process, "list_image_files", lambda directory: sorted(directory.glob("*.jpg")))
    monkeypatch.setattr(process, "download_thumbnail", lambda thumbnail_url, output_path: (write_file(output_path, b"thumb") or output_path))
    monkeypatch.setattr(process, "create_thumbnail_fallback", lambda **kwargs: None)

    def fake_temporal(**kwargs):
        kwargs["output_path"].write_text("{}", encoding="utf-8")
        return {
            "summary": {
                "temporalInstabilityScore": 0.3,
                "aiVisualRiskScore": 0.4,
                "objectDisappearanceRisk": 0.2,
                "riskSignals": ["large_visual_change_without_scene_cut"],
            }
        }

    def fake_visual_events(**kwargs):
        kwargs["output_path"].write_text("{}", encoding="utf-8")
        return {
            "summary": {"authenticityRiskScore": 0.5},
            "eventWindowConsistency": {"overallTemporalAuthenticityRisk": 0.45},
            "frames": [],
        }

    def fake_keyframes_stream(**kwargs):
        kwargs["output_path"].write_text("{}", encoding="utf-8")
        yield {"kind": "result", "payload": {"frames": []}}

    class FakeMetadataAnalyzer:
        def __init__(self, url, path):
            self.url = url
            self.path = path

        def analyze(self, **kwargs):
            return {
                "metadata_score": 0.2,
                "reasons": ["ok"],
                "rule_results": {"rule": True},
                "collection_errors": [],
            }

    def fake_upload(**kwargs):
        if kwargs["bucket"] == process.STORAGE_BUCKETS["rawVideos"]:
            raise process.SupabaseStorageUploadError(
                storage_path=kwargs["storage_path"],
                status_code=413,
                message="payload too large",
            )
        return kwargs["storage_path"]

    monkeypatch.setattr(process, "analyze_temporal_consistency", fake_temporal)
    monkeypatch.setattr(process, "analyze_visual_events", fake_visual_events)
    monkeypatch.setattr(process, "transcribe_audio_with_openai", lambda path: {"text": "transcript"})
    monkeypatch.setattr(process, "analyze_keyframes_stream", fake_keyframes_stream)
    monkeypatch.setattr(
        process,
        "assess_repost_history",
        lambda *args, **kwargs: ({}, "2025-01-01", {"isRepost": False, "matches": []}, 0.1),
    )
    monkeypatch.setattr(process, "MetadataAnalyzer", FakeMetadataAnalyzer)
    monkeypatch.setattr(
        process,
        "analyze_claim",
        lambda **kwargs: {
            "ok": True,
            "claim": "claim",
            "verdict": "unverified",
            "confidence": 0.5,
            "summary": "summary",
            "evidence": [],
            "misleadingProbability": 0.2,
            "visualAuthenticityRisk": 0.4,
            "visualMetadataQuality": {"frameCount": 1},
        },
    )
    monkeypatch.setattr(
        process,
        "analyze_thumbnail_clickbait",
        lambda **kwargs: {
            "ok": True,
            "clickbaitScore": 0.3,
            "riskLevel": "low",
            "thumbnailSummary": "thumbnail",
            "rationale": "matches",
            "mismatches": [],
            "supportingSignals": ["same scene"],
            "error": None,
        },
    )
    monkeypatch.setattr(process, "ensure_storage_buckets", lambda buckets: None)
    monkeypatch.setattr(process, "upload_to_supabase_storage", fake_upload)
    monkeypatch.setattr(
        process,
        "persist_analysis_record",
        lambda **kwargs: {"ok": False, "videoId": None, "error": "db down", "skipped": False},
    )

    events = list(
        process.process_youtube_video(
            "https://www.youtube.com/watch?v=abc123",
            fast_processing_mode=False,
        )
    )

    progress_stages = [event.get("stage", "") for event in events]
    result = events[-1]["result"]
    assert events[-1]["type"] == "complete"
    assert "Raw video too large; continuing with analysis uploads" in progress_stages
    assert result["rawVideoPath"] is None
    assert "too large" in result["rawVideoUploadSkippedReason"]
    assert result["thumbnailPath"] is not None
    assert result["metadataScore"] == 0.2
    assert result["databaseSaveOk"] is False


def test_process_youtube_video_invalid_url_returns_error():
    events = list(process.process_youtube_video("not a url"))

    assert events[0]["type"] == "progress"
    assert events[-1]["type"] == "error"
    assert "Paste a valid" in events[-1]["message"]
