import json
import shutil
import time
import traceback
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import (
    FRAME_SAMPLE_RATE,
    FAST_PROCESSING_MODE,
    KEYFRAME_INTERVAL_SECONDS,
    KEYFRAME_SCENE_THRESHOLD,
    MAX_KEYFRAMES_TO_ANALYZE,
    REPOST_ASSESSMENT_ENABLED,
    DATABASE_SAVE_ENABLED,
    STORAGE_BUCKETS,
    TRANSCRIPTION_LEAD_IN_SECONDS,
    UPLOAD_RAW_VIDEO,
    UPLOADS_ROOT,
)
from .claim_analysis import analyze_claim
from .download import download_video_with_info
from .keyframes import analyze_keyframes_stream
from .media import (
    compute_file_sha256,
    create_audio_with_lead_in,
    extract_audio,
    extract_keyframes,
    extract_sampled_frames,
    list_image_files,
)
from .storage import (
    SupabaseStorageUploadError,
    ensure_storage_buckets,
    upload_to_supabase_storage,
)
from .temporal import analyze_temporal_consistency
from .thumbnail import (
    analyze_thumbnail_clickbait,
    create_thumbnail_fallback,
    download_thumbnail,
    get_thumbnail_url_from_info,
)
from .transcribe import transcribe_audio_with_openai
from .metadata_analyzer import MetadataAnalyzer
from .visual_events import analyze_visual_events
from .youtube import parse_video_url, safe_segment


UPLOAD_WORKERS = 6


def _assess_repost_history(
    file_sha256: str,
    *,
    original_url: str,
    download_info: dict,
) -> tuple[dict, str | None, dict, float | None]:
    if not REPOST_ASSESSMENT_ENABLED:
        skipped = {
            "isRepost": False,
            "repostProbability": None,
            "matches": [],
            "rationale": "Repost assessment disabled or DATABASE_URL is not configured.",
            "skipped": True,
            "skipReason": "Repost assessment disabled or DATABASE_URL is not configured.",
        }
        return skipped, None, skipped, None

    from storage.services.reposts import (
        extract_repost_match_date,
        json_safe_assessment,
        repost_risk_score,
        run_repost_assessment_sync,
    )

    assessment = run_repost_assessment_sync(
        file_sha256=file_sha256,
        embedding=None,
        original_url=original_url,
        uploader_handle=download_info.get("uploader_id") or download_info.get("channel"),
        upload_date=download_info.get("upload_date"),
    )
    result = json_safe_assessment(assessment)
    return (
        assessment,
        extract_repost_match_date(assessment),
        result,
        repost_risk_score(assessment),
    )


def _persist_analysis_record(
    *,
    original_url: str,
    platform: str,
    file_sha256: str,
    download_info: dict,
    transcript: dict,
    raw_video_storage_path: str | None,
    thumbnail_storage_path: str | None,
    transcript_storage_path: str,
    claim_analysis: dict,
    thumbnail_clickbait_analysis: dict,
    metadata_analysis: dict,
    repost_result: dict,
    repost_risk: float | None,
    analysis_paths: dict[str, str | None],
) -> dict:
    if not DATABASE_SAVE_ENABLED:
        return {
            "ok": False,
            "videoId": None,
            "error": "Database save disabled or DATABASE_URL is not configured.",
            "skipped": True,
        }

    from storage.services.db_videos import (
        build_db_video_payload,
        persist_db_video_sync,
    )

    payload = build_db_video_payload(
        original_url=original_url,
        platform=platform,
        file_sha256=file_sha256,
        download_info=download_info,
        transcript_text=transcript.get("text"),
        raw_video_path=raw_video_storage_path,
        thumbnail_path=thumbnail_storage_path,
        transcript_path=transcript_storage_path,
        claim_analysis=claim_analysis,
        thumbnail_clickbait_analysis=thumbnail_clickbait_analysis,
        metadata_analysis=metadata_analysis,
        repost_result=repost_result,
        repost_risk=repost_risk,
        analysis_paths=analysis_paths,
    )
    return persist_db_video_sync(payload)


def select_keyframes_for_analysis(
    *,
    keyframe_paths: list[Path],
    keyframe_timestamps: list[float | None],
    limit: int,
) -> tuple[list[Path], list[float | None]]:
    if limit <= 0:
        return [], []
    if limit == 1:
        timestamp = keyframe_timestamps[0] if keyframe_timestamps else None
        return keyframe_paths[:1], [timestamp] if keyframe_paths else []
    if len(keyframe_paths) <= limit:
        return keyframe_paths, keyframe_timestamps[: len(keyframe_paths)]

    last_index = len(keyframe_paths) - 1
    selected_indexes = sorted(
        {
            round(index * last_index / (limit - 1))
            for index in range(limit)
        }
    )
    selected_paths = [keyframe_paths[index] for index in selected_indexes]
    selected_timestamps = [
        keyframe_timestamps[index] if index < len(keyframe_timestamps) else None
        for index in selected_indexes
    ]
    return selected_paths, selected_timestamps


def process_youtube_video(
    video_url: str,
    *,
    fast_processing_mode: bool | None = None,
) -> Generator[dict, None, None]:
    use_fast_processing_mode = (
        FAST_PROCESSING_MODE if fast_processing_mode is None else fast_processing_mode
    )

    def send(event: dict) -> dict:
        return event

    job_dir: Path | None = None
    stage = "Starting"

    try:
        stage = "Reading request"
        yield send({"type": "progress", "progress": 3, "stage": stage})

        video_info = parse_video_url(video_url)
        if not video_info:
            yield send(
                {
                    "type": "error",
                    "message": (
                        "Paste a valid YouTube, TikTok, Instagram, or direct video URL."
                    ),
                }
            )
            return

        platform = video_info["platform"]
        video_id = video_info["id"]
        original_url = video_info["url"]
        job_id = f"{safe_segment(video_id)}-{int(time.time() * 1000)}"
        storage_prefix = f"videos/{platform}/{job_id}"
        job_dir = UPLOADS_ROOT / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        audio_path = job_dir / "audio.wav"
        transcription_audio_path = job_dir / "audio-for-transcript.wav"
        transcript_path = job_dir / "transcript.json"
        keyframe_analysis_path = job_dir / "keyframe-analysis.json"
        temporal_analysis_path = job_dir / "temporal-consistency.json"
        visual_event_analysis_path = job_dir / "visual-event-analysis.json"
        claim_analysis_path = job_dir / "claim-analysis.json"
        metadata_analysis_path = job_dir / "metadata-analysis.json"
        thumbnail_path = job_dir / "thumbnail.jpg"
        thumbnail_analysis_path = job_dir / "thumbnail-clickbait-analysis.json"
        repost_analysis_path = job_dir / "repost-analysis.json"
        frames_dir = job_dir / "frames"
        keyframes_dir = job_dir / "keyframes"
        frames_dir.mkdir(parents=True, exist_ok=True)
        keyframes_dir.mkdir(parents=True, exist_ok=True)

        stage = "Preparing workspace"
        yield send({"type": "progress", "progress": 8, "stage": stage})
        stage = "Preparing downloader"
        yield send({"type": "progress", "progress": 12, "stage": stage})
        stage = "Downloading video"
        yield send({"type": "progress", "progress": 18, "stage": stage})

        video_path, download_info = download_video_with_info(original_url, job_dir)
        file_sha256 = compute_file_sha256(video_path)
        thumbnail_url = get_thumbnail_url_from_info(download_info)

        stage = "Extracting audio"
        yield send({"type": "progress", "progress": 35, "stage": stage})
        extract_audio(video_path, audio_path)

        yield send(
            {
                "type": "progress",
                "progress": 43,
                "stage": "Preparing audio for transcription",
            }
        )
        create_audio_with_lead_in(audio_path, transcription_audio_path)

        yield send({"type": "progress", "progress": 50, "stage": "Extracting sampled frames"})
        frame_sample_rate = extract_sampled_frames(video_path, frames_dir)

        yield send({"type": "progress", "progress": 56, "stage": "Extracting keyframes"})
        keyframe_timestamps = extract_keyframes(video_path, keyframes_dir)

        frame_paths = list_image_files(frames_dir)
        keyframe_paths = list_image_files(keyframes_dir)
        local_thumbnail_path = None
        if thumbnail_url:
            local_thumbnail_path = download_thumbnail(
                thumbnail_url=thumbnail_url,
                output_path=thumbnail_path,
            )
        if local_thumbnail_path is None:
            local_thumbnail_path = create_thumbnail_fallback(
                keyframe_paths=keyframe_paths,
                output_path=thumbnail_path,
            )
        keyframes_for_analysis, timestamps_for_analysis = select_keyframes_for_analysis(
            keyframe_paths=keyframe_paths,
            keyframe_timestamps=keyframe_timestamps,
            limit=MAX_KEYFRAMES_TO_ANALYZE,
        )

        yield send({"type": "progress", "progress": 59, "stage": "Checking temporal consistency"})
        temporal_analysis = analyze_temporal_consistency(
            frame_paths=frame_paths,
            keyframe_timestamps=keyframe_timestamps,
            output_path=temporal_analysis_path,
            frame_sample_rate=frame_sample_rate,
        )


        if use_fast_processing_mode:
            visual_event_analysis = {
                "summary": {},
                "frames": [],
                "eventWindowConsistency": {},
                "skipped": True,
                "skipReason": "FAST_PROCESSING_MODE=true",
            }
            visual_event_analysis_path.write_text(
                json.dumps(visual_event_analysis, indent=2),
                encoding="utf-8",
            )
        else:
            yield send({"type": "progress", "progress": 60, "stage": "Scanning visual event frames"})
            visual_event_analysis = analyze_visual_events(
                frame_paths=frame_paths,
                temporal_analysis=temporal_analysis,
                output_path=visual_event_analysis_path,
            )

        video_suffix = video_path.suffix or ".mp4"
        raw_video_storage_path = f"{storage_prefix}/raw/original{video_suffix}"
        audio_storage_path = f"{storage_prefix}/audio/audio.wav"
        thumbnail_storage_path = f"{storage_prefix}/thumbnails/thumbnail.jpg"
        transcript_storage_path = f"{storage_prefix}/transcripts/transcript-und.json"
        keyframe_analysis_storage_path = (
            f"{storage_prefix}/analysis/keyframe-analysis.json"
        )
        temporal_analysis_storage_path = (
            f"{storage_prefix}/analysis/temporal-consistency.json"
        )
        visual_event_analysis_storage_path = (
            f"{storage_prefix}/analysis/visual-event-analysis.json"
        )
        claim_analysis_storage_path = f"{storage_prefix}/analysis/claim-analysis.json"
        metadata_analysis_storage_path = (
            f"{storage_prefix}/analysis/metadata-analysis.json"
        )
        thumbnail_analysis_storage_path = (
            f"{storage_prefix}/analysis/thumbnail-clickbait-analysis.json"
        )
        repost_analysis_storage_path = f"{storage_prefix}/analysis/repost-analysis.json"

        yield send({"type": "progress", "progress": 62, "stage": "Transcribing audio"})
        transcript = transcribe_audio_with_openai(transcription_audio_path)
        transcript["source"] = {
            "url": original_url,
            "platform": platform,
            "externalId": video_id,
            "audioPath": audio_storage_path,
            "transcriptionLeadInSeconds": TRANSCRIPTION_LEAD_IN_SECONDS,
        }
        transcript_path.write_text(json.dumps(transcript, indent=2), encoding="utf-8")

        yield send({"type": "progress", "progress": 70, "stage": "Analyzing keyframes"})

        keyframe_analysis = None
        for event in analyze_keyframes_stream(
            keyframe_paths=keyframes_for_analysis,
            keyframe_timestamps=timestamps_for_analysis,
            output_path=keyframe_analysis_path,
        ):
            if event.get("kind") == "progress":
                payload = event["payload"]
                index = payload.get("index", 0)
                total = max(payload.get("total", 1), 1)
                progress_value = 70 + round((index / total) * 8)
                yield send(
                    {
                        "type": "progress",
                        "progress": progress_value,
                        "stage": f"Analyzing keyframe {index} of {total}",
                    }
                )
            elif event.get("kind") == "result":
                keyframe_analysis = event["payload"]

        if keyframe_analysis is None:
            raise RuntimeError("Keyframe analysis did not complete.")

        yield send({"type": "progress", "progress": 78, "stage": "Checking repost history"})
        repost_assessment, repost_match_date, repost_result, repost_risk = (
            _assess_repost_history(
                file_sha256,
                original_url=original_url,
                download_info=download_info,
            )
        )

        repost_analysis_path.write_text(
            json.dumps(repost_result, indent=2),
            encoding="utf-8",
        )

        yield send({"type": "progress", "progress": 79, "stage": "Analyzing metadata"})
        if use_fast_processing_mode:
            metadata_analysis = {
                "metadata_score": None,
                "reasons": [],
                "rule_results": {},
                "collection_errors": [],
                "skipped": True,
                "skipReason": "FAST_PROCESSING_MODE=true",
            }
        else:
            metadata_analysis = MetadataAnalyzer(original_url, video_path).analyze(
                transcript_text=transcript.get("text"),
                repost_match_date=repost_match_date,
            )
        metadata_analysis["source"] = {
            "url": original_url,
            "platform": platform,
            "externalId": video_id,
            "transcriptPath": transcript_storage_path,
        }
        metadata_analysis_path.write_text(
            json.dumps(metadata_analysis, indent=2),
            encoding="utf-8",
        )

        yield send({"type": "progress", "progress": 82, "stage": "Fact-checking claim"})
        claim_analysis = analyze_claim(
            transcript=transcript,
            keyframe_analysis=keyframe_analysis,
            temporal_analysis=temporal_analysis,
            visual_event_analysis=visual_event_analysis,
        )
        claim_analysis["source"] = {
            "url": original_url,
            "platform": platform,
            "externalId": video_id,
            "transcriptPath": transcript_storage_path,
            "keyframeAnalysisPath": keyframe_analysis_storage_path,
            "temporalAnalysisPath": temporal_analysis_storage_path,
            "visualEventAnalysisPath": visual_event_analysis_storage_path,
        }
        claim_analysis_path.write_text(
            json.dumps(claim_analysis, indent=2), encoding="utf-8"
        )

        yield send({"type": "progress", "progress": 84, "stage": "Checking thumbnail fit"})
        if use_fast_processing_mode:
            thumbnail_clickbait_analysis = {
                "ok": False,
                "clickbaitScore": None,
                "riskLevel": "unknown",
                "thumbnailSummary": "",
                "rationale": "",
                "mismatches": [],
                "supportingSignals": [],
                "error": "FAST_PROCESSING_MODE=true",
            }
        else:
            thumbnail_clickbait_analysis = analyze_thumbnail_clickbait(
                thumbnail_path=local_thumbnail_path,
                transcript=transcript,
                claim_analysis=claim_analysis,
                keyframe_analysis=keyframe_analysis,
                visual_event_analysis=visual_event_analysis,
            )
        thumbnail_analysis_path.write_text(
            json.dumps(thumbnail_clickbait_analysis, indent=2),
            encoding="utf-8",
        )

        stage = "Uploading raw video"
        yield send({"type": "progress", "progress": 86, "stage": stage})
        raw_video_upload_skipped_reason = None
        if not UPLOAD_RAW_VIDEO:
            raw_video_storage_path = None
            raw_video_upload_skipped_reason = (
                "UPLOAD_RAW_VIDEO=false skips storing the full MP4. RealReel kept "
                "the transcript, thumbnail, and analysis artifacts."
            )
        elif use_fast_processing_mode:
            raw_video_storage_path = None
            raw_video_upload_skipped_reason = "FAST_PROCESSING_MODE=true skips raw MP4 upload."
        else:
            try:
                upload_to_supabase_storage(
                    bucket=STORAGE_BUCKETS["rawVideos"],
                    storage_path=raw_video_storage_path,
                    local_path=video_path,
                    content_type="video/mp4",
                )
            except SupabaseStorageUploadError as exc:
                if not exc.is_payload_too_large:
                    raise
                raw_video_storage_path = None
                raw_video_upload_skipped_reason = (
                    "Raw video was too large for Supabase Storage, so RealReel skipped "
                    "storing the full MP4 and kept the transcript, thumbnail, and analysis artifacts."
                )
                yield send(
                    {
                        "type": "progress",
                        "progress": 88,
                        "stage": "Raw video too large; continuing with analysis uploads",
                    }
                )

        stage = "Uploading analysis artifacts"
        yield send({"type": "progress", "progress": 90, "stage": stage})
        ensure_storage_buckets(set(STORAGE_BUCKETS.values()))
        upload_tasks = [
            {
                "name": "audio",
                "bucket": STORAGE_BUCKETS["audio"],
                "storage_path": audio_storage_path,
                "local_path": audio_path,
                "content_type": "audio/wav",
            },
            {
                "name": "transcript",
                "bucket": STORAGE_BUCKETS["transcripts"],
                "storage_path": transcript_storage_path,
                "local_path": transcript_path,
                "content_type": "application/json",
            },
            {
                "name": "keyframe analysis",
                "bucket": STORAGE_BUCKETS["analysis"],
                "storage_path": keyframe_analysis_storage_path,
                "local_path": keyframe_analysis_path,
                "content_type": "application/json",
            },
            {
                "name": "temporal analysis",
                "bucket": STORAGE_BUCKETS["analysis"],
                "storage_path": temporal_analysis_storage_path,
                "local_path": temporal_analysis_path,
                "content_type": "application/json",
            },
            {
                "name": "visual event analysis",
                "bucket": STORAGE_BUCKETS["analysis"],
                "storage_path": visual_event_analysis_storage_path,
                "local_path": visual_event_analysis_path,
                "content_type": "application/json",
            },
            {
                "name": "claim analysis",
                "bucket": STORAGE_BUCKETS["analysis"],
                "storage_path": claim_analysis_storage_path,
                "local_path": claim_analysis_path,
                "content_type": "application/json",
            },
            {
                "name": "metadata analysis",
                "bucket": STORAGE_BUCKETS["analysis"],
                "storage_path": metadata_analysis_storage_path,
                "local_path": metadata_analysis_path,
                "content_type": "application/json",
            },
            {
                "name": "thumbnail analysis",
                "bucket": STORAGE_BUCKETS["analysis"],
                "storage_path": thumbnail_analysis_storage_path,
                "local_path": thumbnail_analysis_path,
                "content_type": "application/json",
            },
            {
                "name": "repost analysis",
                "bucket": STORAGE_BUCKETS["analysis"],
                "storage_path": repost_analysis_storage_path,
                "local_path": repost_analysis_path,
                "content_type": "application/json",
            },
        ]
        if local_thumbnail_path is not None:
            upload_tasks.append(
                {
                    "name": "thumbnail",
                    "bucket": STORAGE_BUCKETS["thumbnails"],
                    "storage_path": thumbnail_storage_path,
                    "local_path": local_thumbnail_path,
                    "content_type": "image/jpeg",
                }
            )
        with ThreadPoolExecutor(max_workers=min(UPLOAD_WORKERS, len(upload_tasks))) as executor:
            futures = {
                executor.submit(
                    upload_to_supabase_storage,
                    bucket=task["bucket"],
                    storage_path=task["storage_path"],
                    local_path=task["local_path"],
                    content_type=task["content_type"],
                ): task["name"]
                for task in upload_tasks
            }
            completed_uploads = 0
            for future in as_completed(futures):
                future.result()
                completed_uploads += 1
                progress = 90 + round((completed_uploads / len(upload_tasks)) * 7)
                yield send(
                    {
                        "type": "progress",
                        "progress": progress,
                        "stage": f"Uploaded {futures[future]}",
                    }
                )

        yield send({"type": "progress", "progress": 97, "stage": "Saving analysis record"})
        database_save = _persist_analysis_record(
            original_url=original_url,
            platform=platform,
            file_sha256=file_sha256,
            download_info=download_info,
            transcript=transcript,
            raw_video_storage_path=raw_video_storage_path,
            thumbnail_storage_path=thumbnail_storage_path
            if local_thumbnail_path is not None
            else None,
            transcript_storage_path=transcript_storage_path,
            claim_analysis=claim_analysis,
            thumbnail_clickbait_analysis=thumbnail_clickbait_analysis,
            metadata_analysis=metadata_analysis,
            repost_result=repost_result,
            repost_risk=repost_risk,
            analysis_paths={
                "rawVideo": raw_video_storage_path,
                "audio": audio_storage_path,
                "thumbnail": thumbnail_storage_path
                if local_thumbnail_path is not None
                else None,
                "transcript": transcript_storage_path,
                "keyframeAnalysis": keyframe_analysis_storage_path,
                "temporalAnalysis": temporal_analysis_storage_path,
                "visualEventAnalysis": visual_event_analysis_storage_path,
                "claimAnalysis": claim_analysis_storage_path,
                "metadataAnalysis": metadata_analysis_storage_path,
                "thumbnailAnalysis": thumbnail_analysis_storage_path,
                "repostAnalysis": repost_analysis_storage_path,
            },
        )

        yield send({"type": "progress", "progress": 98, "stage": "Cleaning temporary files"})
        shutil.rmtree(job_dir, ignore_errors=True)
        job_dir = None

        yield send(
            {
                "type": "complete",
                "progress": 100,
                "stage": "Complete",
                "result": {
                    "success": True,
                    "platform": platform,
                    "sourceUrl": original_url,
                    "rawVideoPath": raw_video_storage_path,
                    "rawVideoUploadSkippedReason": raw_video_upload_skipped_reason,
                    "audioPath": audio_storage_path,
                    "thumbnailPath": thumbnail_storage_path
                    if local_thumbnail_path is not None
                    else None,
                    "transcriptPath": transcript_storage_path,
                    "keyframeAnalysisPath": keyframe_analysis_storage_path,
                    "temporalAnalysisPath": temporal_analysis_storage_path,
                    "visualEventAnalysisPath": visual_event_analysis_storage_path,
                    "claimAnalysisPath": claim_analysis_storage_path,
                    "metadataAnalysisPath": metadata_analysis_storage_path,
                    "thumbnailAnalysisPath": thumbnail_analysis_storage_path,
                    "repostAnalysisPath": repost_analysis_storage_path,
                    "fileSha256": file_sha256,
                    "isRepost": repost_result.get("isRepost"),
                    "repostProbability": repost_result.get("repostProbability"),
                    "repostRisk": repost_risk,
                    "repostRationale": repost_result.get("rationale"),
                    "repostMatches": repost_result.get("matches", []),
                    "repostAssessmentSkipped": repost_result.get("skipped", False),
                    "databaseSaveOk": database_save.get("ok"),
                    "databaseVideoId": database_save.get("videoId"),
                    "databaseSaveError": database_save.get("error"),
                    "databaseSaveSkipped": database_save.get("skipped", False),
                    "metadataScore": metadata_analysis.get("metadata_score"),
                    "metadataReasons": metadata_analysis.get("reasons", []),
                    "metadataRuleResults": metadata_analysis.get("rule_results", {}),
                    "metadataCollectionErrors": metadata_analysis.get(
                        "collection_errors", []
                    ),
                    "claimAnalysisOk": claim_analysis.get("ok"),
                    "claim": claim_analysis.get("claim"),
                    "claimVerdict": claim_analysis.get("verdict"),
                    "claimConfidence": claim_analysis.get("confidence"),
                    "recommendedAction": claim_analysis.get("recommendedAction"),
                    "misleadingProbability": claim_analysis.get("misleadingProbability"),
                    "misleadingProbabilityRationale": claim_analysis.get(
                        "misleadingProbabilityRationale"
                    ),
                    "visualAuthenticityRisk": claim_analysis.get(
                        "visualAuthenticityRisk"
                    ),
                    "visualAuthenticityRationale": claim_analysis.get(
                        "visualAuthenticityRationale"
                    ),
                    "visualAuthenticitySignals": claim_analysis.get(
                        "visualAuthenticitySignals", []
                    ),
                    "depictedEvent": claim_analysis.get("depictedEvent"),
                    "claimSummary": claim_analysis.get("summary"),
                    "thumbnailClickbaitScore": thumbnail_clickbait_analysis.get(
                        "clickbaitScore"
                    ),
                    "thumbnailClickbaitRiskLevel": thumbnail_clickbait_analysis.get(
                        "riskLevel"
                    ),
                    "thumbnailSummary": thumbnail_clickbait_analysis.get(
                        "thumbnailSummary"
                    ),
                    "thumbnailClickbaitRationale": thumbnail_clickbait_analysis.get(
                        "rationale"
                    ),
                    "thumbnailClickbaitMismatches": thumbnail_clickbait_analysis.get(
                        "mismatches", []
                    ),
                    "thumbnailClickbaitSupportingSignals": thumbnail_clickbait_analysis.get(
                        "supportingSignals", []
                    ),
                    "thumbnailClickbaitError": thumbnail_clickbait_analysis.get("error"),
                    "claimEvidenceCount": len(claim_analysis.get("evidence") or []),
                    "transcriptText": transcript.get("text") or "",
                    "buckets": STORAGE_BUCKETS,
                    "frameCount": len(frame_paths),
                    "frameRate": frame_sample_rate,
                    "keyFrameCount": len(keyframe_paths),
                    "analyzedKeyFrameCount": len(keyframes_for_analysis),
                    "maxKeyframesToAnalyze": MAX_KEYFRAMES_TO_ANALYZE,
                    "ocrTextFrameCount": sum(
                        1
                        for frame in keyframe_analysis["frames"]
                        if frame.get("ocr", {}).get("indicators", {}).get("hasText")
                    ),
                    "visionSignalFrameCount": sum(
                        1
                        for frame in keyframe_analysis["frames"]
                        if (frame.get("vision", {}).get("indicators", {}).get("contextSignals"))
                        or (
                            frame.get("vision", {})
                            .get("indicators", {})
                            .get("synthetic", {})
                            .get("signals")
                        )
                    ),
                    "visionTextFrameCount": sum(
                        1
                        for frame in keyframe_analysis["frames"]
                        if frame.get("vision", {})
                        .get("indicators", {})
                        .get("visibleText")
                    ),
                    "visionSceneDescriptionFrameCount": sum(
                        1
                        for frame in keyframe_analysis["frames"]
                        if (
                            frame.get("vision", {})
                            .get("indicators", {})
                            .get("sceneDescription")
                        )
                    ),
                    "visionErrorCount": sum(
                        1
                        for frame in keyframe_analysis["frames"]
                        if frame.get("vision", {}).get("error")
                    ),
                    "visionErrors": [
                        frame.get("vision", {}).get("error")
                        for frame in keyframe_analysis["frames"]
                        if frame.get("vision", {}).get("error")
                    ][:3],
                    "visualMetadataQuality": claim_analysis.get(
                        "visualMetadataQuality"
                    ),
                    "temporalInstabilityScore": temporal_analysis["summary"].get(
                        "temporalInstabilityScore"
                    ),
                    "aiVisualRiskScore": temporal_analysis["summary"].get(
                        "aiVisualRiskScore"
                    ),
                    "objectDisappearanceRisk": temporal_analysis["summary"].get(
                        "objectDisappearanceRisk"
                    ),
                    "temporalRiskSignals": temporal_analysis["summary"].get(
                        "riskSignals", []
                    ),
                    "visualEventSummary": visual_event_analysis.get("summary", {}),
                    "eventWindowConsistency": visual_event_analysis.get(
                        "eventWindowConsistency"
                    ),
                    "crossModalHintCount": sum(
                        len(frame.get("hints") or [])
                        for frame in keyframe_analysis["frames"]
                    ),
                    "keyframeSceneThreshold": KEYFRAME_SCENE_THRESHOLD,
                    "keyframeIntervalSeconds": KEYFRAME_INTERVAL_SECONDS,
                    "message": (
                        "Video processed. Raw video, audio, transcript, and "
                        "analysis files were uploaded; local frames and keyframes were "
                        "deleted after processing."
                    ),
                },
            }
        )
    except Exception as exc:
        message = str(exc) or "Failed to process YouTube video."
        print(f"[process-youtube] {stage} failed: {message}", flush=True)
        traceback.print_exc()
        yield send(
            {
                "type": "error",
                "message": f"{stage}: {message}",
            }
        )
    finally:
        if job_dir and job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
