"use client";

import { useEffect, useMemo, useState } from "react";

type PreviewSource =
  | { type: "empty" }
  | { type: "invalid" }
  | { type: "social"; platform: string; url: string }
  | { type: "video"; src: string }
  | { type: "iframe"; src: string; title: string; orientation?: "portrait" | "landscape" };

type ProcessingResult = {
  success: boolean;
  rawVideoPath?: string | null;
  rawVideoUploadSkippedReason?: string | null;
  audioPath?: string;
  transcriptPath?: string;
  keyframeAnalysisPath?: string;
  temporalAnalysisPath?: string;
  claimAnalysisPath?: string;
  thumbnailPath?: string | null;
  thumbnailAnalysisPath?: string;
  claimAnalysisOk?: boolean;
  claim?: string | null;
  claimVerdict?: string;
  claimConfidence?: number | null;
  recommendedAction?: string;
  misleadingProbability?: number | null;
  misleadingProbabilityRationale?: string;
  visualAuthenticityRisk?: number | null;
  visualAuthenticityRationale?: string;
  visualAuthenticitySignals?: string[];
  depictedEvent?: string | null;
  claimSummary?: string;
  thumbnailClickbaitScore?: number | null;
  thumbnailClickbaitRiskLevel?: string;
  thumbnailSummary?: string;
  thumbnailClickbaitRationale?: string;
  thumbnailClickbaitMismatches?: string[];
  thumbnailClickbaitSupportingSignals?: string[];
  thumbnailClickbaitError?: string | null;
  claimEvidenceCount?: number;
  transcriptText?: string;
  frameCount?: number;
  frameRate?: number;
  keyFrameCount?: number;
  analyzedKeyFrameCount?: number;
  maxKeyframesToAnalyze?: number;
  ocrTextFrameCount?: number;
  visionSignalFrameCount?: number;
  visionTextFrameCount?: number;
  visionSceneDescriptionFrameCount?: number;
  visionErrorCount?: number;
  visionErrors?: string[];
  visualMetadataQuality?: {
    frameCount?: number;
    meaningfulFrameCount?: number;
    visionErrorCount?: number;
    sampleVisionErrors?: string[];
  };
  temporalInstabilityScore?: number | null;
  aiVisualRiskScore?: number | null;
  objectDisappearanceRisk?: number | null;
  temporalRiskSignals?: string[];
  visualEventSummary?: {
    authenticityRiskScore?: number | null;
    authenticitySignals?: string[];
    authenticityRiskSignals?: string[];
    authenticityRealismSignals?: string[];
    authenticityRationales?: string[];
  };
  eventWindowConsistency?: {
    physicalConsistencyRisk?: number | null;
    subjectReactionRisk?: number | null;
    lightingContinuityRisk?: number | null;
    debrisMotionRisk?: number | null;
    cameraContinuityRisk?: number | null;
    overallTemporalAuthenticityRisk?: number | null;
    rationale?: string;
    riskSignals?: string[];
    consistencySignals?: string[];
  };
  crossModalHintCount?: number;
  keyframeSceneThreshold?: number;
  message?: string;
}

type ProgressEvent =
  | { type: "progress"; progress: number; stage: string }
  | { type: "complete"; progress: number; stage: string; result: ProcessingResult }
  | { type: "error"; message: string };

function getPreviewSource(input: string): PreviewSource {
  const trimmedInput = input.trim();

  if (!trimmedInput) {
    return { type: "empty" };
  }

  try {
    const url = new URL(trimmedInput);
    const hostname = url.hostname.replace(/^www\./, "");

    if (hostname === "youtube.com" || hostname === "m.youtube.com") {
      const videoId = url.searchParams.get("v") || getPathSegment(url, "shorts");

      if (videoId) {
        return {
          type: "iframe",
          src: `https://www.youtube.com/embed/${videoId}`,
          title: "YouTube video preview",
          orientation: url.pathname.includes("/shorts/") ? "portrait" : "landscape",
        };
      }
    }

    if (hostname === "youtu.be") {
      const videoId = url.pathname.split("/").filter(Boolean)[0];

      if (videoId) {
        return {
          type: "iframe",
          src: `https://www.youtube.com/embed/${videoId}`,
          title: "YouTube video preview",
        };
      }
    }

    if (hostname === "instagram.com") {
      const shortcode =
        getPathSegment(url, "reel") ||
        getPathSegment(url, "reels") ||
        getPathSegment(url, "p");

      if (shortcode) {
        return {
          type: "iframe",
          src: `https://www.instagram.com/reel/${shortcode}/embed`,
          title: "Instagram reel preview",
          orientation: "portrait",
        };
      }

      return { type: "social", platform: "Instagram", url: url.href };
    }

    if (hostname === "tiktok.com" || hostname.endsWith(".tiktok.com")) {
      const videoId = getPathSegment(url, "video");

      if (videoId) {
        return {
          type: "iframe",
          src: `https://www.tiktok.com/embed/v2/${videoId}`,
          title: "TikTok video preview",
          orientation: "portrait",
        };
      }

      return { type: "social", platform: "TikTok", url: url.href };
    }

    if (hostname.includes("vimeo.com")) {
      const videoId = url.pathname.split("/").filter(Boolean).at(-1);

      if (videoId) {
        return {
          type: "iframe",
          src: `https://player.vimeo.com/video/${videoId}`,
          title: "Vimeo video preview",
        };
      }
    }

    return { type: "video", src: url.href };
  } catch {
    return { type: "invalid" };
  }
}

function getPathSegment(url: URL, label: string) {
  const parts = url.pathname.split("/").filter(Boolean);
  const index = parts.indexOf(label);
  return index >= 0 ? parts[index + 1] : null;
}

export default function Home() {
  const [videoUrl, setVideoUrl] = useState("");
  const preview = useMemo(() => getPreviewSource(videoUrl), [videoUrl]);

  const [isProcessing, setIsProcessing] = useState(false);
  const [results, setResults] = useState<ProcessingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressStage, setProgressStage] = useState("");
  const [fastProcessingMode, setFastProcessingMode] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("fastProcessingMode");
    if (saved === "true") {
      setFastProcessingMode(true);
    }
  }, []);

  function toggleFastProcessingMode() {
    setFastProcessingMode((current) => {
      const next = !current;
      localStorage.setItem("fastProcessingMode", String(next));
      return next;
    });
  }

  async function handleProcessClick() {
    setIsProcessing(true);
    setError(null);
    setResults(null);
    setProgress(0);
    setProgressStage("Starting");

    try {
      const response = await fetch('/api/process-youtube', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ videoUrl, fastProcessingMode }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data.message || 'Something went wrong during processing.');
      }

      if (!response.body) {
        throw new Error('The processing stream did not start.');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim()) {
            continue;
          }

          const event = JSON.parse(line) as ProgressEvent;

          if (event.type === "progress") {
            setProgress(event.progress);
            setProgressStage(event.stage);
          }

          if (event.type === "complete") {
            setProgress(event.progress);
            setProgressStage(event.stage);
            setResults(event.result);
          }

          if (event.type === "error") {
            throw new Error(event.message);
          }
        }
      }
    } catch (err: any) {
      setError(err.message);
      setProgressStage("Failed");
    } finally {
      setIsProcessing(false);
    }
  }

  return (
    <main className="page">
      <section className="hero">
        <p className="eyebrow">RealReel</p>
        <h1>Preview and Process any video URL.</h1>
        <p className="intro">
          Paste a YouTube, TikTok, Instagram, or direct video link, then
          click "Process" to extract audio, frames, and analysis.
        </p>

        <div className="inputGroup">
          <label htmlFor="video-url">Video URL</label>
          <input
            id="video-url"
            type="url"
            value={videoUrl}
            onChange={(event) => setVideoUrl(event.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            disabled={isProcessing}
          />
          <div className="actionRow">
            <button
              type="button"
              className={`modeToggle ${fastProcessingMode ? "modeToggleActive" : ""}`}
              onClick={toggleFastProcessingMode}
              disabled={isProcessing}
              aria-pressed={fastProcessingMode}
            >
              Fast mode: {fastProcessingMode ? "On" : "Off"}
            </button>
            <button onClick={handleProcessClick} disabled={isProcessing || preview.type === 'empty' || preview.type === 'invalid'}>
              {isProcessing ? 'Processing...' : 'Process Video'}
            </button>
          </div>
          {fastProcessingMode && (
            <p className="modeHint">
              Skips visual events, metadata, thumbnail clickbait, and raw video upload.
            </p>
          )}
        </div>
      </section>

      <section
        className={`previewCard ${preview.type === "iframe" && preview.orientation === "portrait" ? "portraitPreview" : ""}`}
        aria-live="polite"
      >
        {preview.type === "empty" && (
          <div className="emptyState">
            <span>Paste a URL above to see the video preview here.</span>
          </div>
        )}

        {preview.type === "invalid" && (
          <div className="emptyState error">
            <span>Please enter a valid full URL, including https://.</span>
          </div>
        )}

        {preview.type === "iframe" && (
          <iframe
            src={preview.src}
            title={preview.title}
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            allowFullScreen
          />
        )}

        {preview.type === "social" && (
          <div className="emptyState">
            <span>{preview.platform} link ready to process.</span>
          </div>
        )}

        {preview.type === "video" && (
          <video controls src={preview.src}>
            Your browser does not support the video tag.
          </video>
        )}
      </section>

      <section className="resultsCard" aria-live="polite">
        {isProcessing && (
          <div className="progressPanel">
            <div className="progressHeader">
              <span>{progressStage || "Processing video"}</span>
              <span>{progress}%</span>
            </div>
            <div className="progressTrack" aria-label="Processing progress">
              <div className="progressFill" style={{ width: `${progress}%` }} />
            </div>
          </div>
        )}
        {error && (
          <div className="emptyState error">
            <span>Error: {error}</span>
          </div>
        )}
        {results && results.success && (
          <div>
            <h3>Uploaded to Storage</h3>
            <p><strong>Raw Video Path:</strong> {results.rawVideoPath || "N/A"}</p>
            {results.rawVideoUploadSkippedReason && (
              <p><strong>Raw Video Upload:</strong> {results.rawVideoUploadSkippedReason}</p>
            )}
            <p><strong>Audio Path:</strong> {results.audioPath}</p>
            <p><strong>Thumbnail Path:</strong> {results.thumbnailPath || "N/A"}</p>
            <p><strong>Transcript Path:</strong> {results.transcriptPath}</p>
            <p><strong>Keyframe Analysis Path:</strong> {results.keyframeAnalysisPath}</p>
            <p><strong>Temporal Analysis Path:</strong> {results.temporalAnalysisPath}</p>
            <p><strong>Claim Analysis Path:</strong> {results.claimAnalysisPath}</p>
            <p><strong>Thumbnail Analysis Path:</strong> {results.thumbnailAnalysisPath}</p>
            <p><strong>Claim:</strong> {results.claim || "No clear factual claim detected"}</p>
            <p><strong>Claim Verdict:</strong> {results.claimVerdict || "unverified"}</p>
            <p><strong>Recommended Action:</strong> {results.recommendedAction || "needs_more_evidence"}</p>
            <p><strong>Claim Confidence:</strong> {typeof results.claimConfidence === "number" ? `${Math.round(results.claimConfidence * 100)}%` : "N/A"}</p>
            <p><strong>Misleading Chance:</strong> {typeof results.misleadingProbability === "number" ? `${Math.round(results.misleadingProbability * 100)}%` : "N/A"}</p>
            <p><strong>Depicted Event:</strong> {results.depictedEvent || "N/A"}</p>
            <p><strong>Visual Authenticity Risk:</strong> {typeof results.visualAuthenticityRisk === "number" ? `${Math.round(results.visualAuthenticityRisk * 100)}%` : "N/A"}</p>
            <p><strong>Visual Authenticity Signals:</strong> {(results.visualAuthenticitySignals || []).join(", ") || "None"}</p>
            <p><strong>Thumbnail Clickbait Score:</strong> {typeof results.thumbnailClickbaitScore === "number" ? `${Math.round(results.thumbnailClickbaitScore * 100)}%` : "N/A"}</p>
            <p><strong>Thumbnail Clickbait Risk:</strong> {results.thumbnailClickbaitRiskLevel || "N/A"}</p>
            {results.thumbnailSummary && (
              <p><strong>Thumbnail Summary:</strong> {results.thumbnailSummary}</p>
            )}
            {results.thumbnailClickbaitRationale && (
              <p><strong>Thumbnail Clickbait Reason:</strong> {results.thumbnailClickbaitRationale}</p>
            )}
            <p><strong>Thumbnail Mismatches:</strong> {(results.thumbnailClickbaitMismatches || []).join(", ") || "None"}</p>
            <p><strong>Thumbnail Supporting Signals:</strong> {(results.thumbnailClickbaitSupportingSignals || []).join(", ") || "None"}</p>
            {results.thumbnailClickbaitError && (
              <p><strong>Thumbnail Clickbait Error:</strong> {results.thumbnailClickbaitError}</p>
            )}
            {results.visualAuthenticityRationale && (
              <p><strong>Visual Authenticity Reason:</strong> {results.visualAuthenticityRationale}</p>
            )}
            {results.misleadingProbabilityRationale && (
              <p><strong>Misleading Score Reason:</strong> {results.misleadingProbabilityRationale}</p>
            )}
            <p><strong>Claim Evidence Sources:</strong> {results.claimEvidenceCount ?? 0}</p>
            {results.claimSummary && (
              <p><strong>Claim Summary:</strong> {results.claimSummary}</p>
            )}
            <p><strong>Sampled Frames Extracted Locally:</strong> {results.frameCount ?? 0}</p>
            <p><strong>Frame Sampling:</strong> {results.frameRate ?? 1} frame per second</p>
            <p><strong>Keyframes Extracted Locally:</strong> {results.keyFrameCount ?? 0}</p>
            <p><strong>Keyframes Analyzed:</strong> {results.analyzedKeyFrameCount ?? 0} of max {results.maxKeyframesToAnalyze ?? 6}</p>
            <p><strong>Keyframes With OCR Text:</strong> {results.ocrTextFrameCount ?? 0}</p>
            <p><strong>Keyframes With Gemini Text:</strong> {results.visionTextFrameCount ?? 0}</p>
            <p><strong>Keyframes With Scene Descriptions:</strong> {results.visionSceneDescriptionFrameCount ?? 0}</p>
            <p><strong>Vision Errors:</strong> {results.visionErrorCount ?? 0}</p>
            {(results.visionErrors || []).map((visionError, index) => (
              <p key={`vision-error-${index}`}><strong>Vision Error {index + 1}:</strong> {visionError}</p>
            ))}
            {results.visualMetadataQuality && (
              <p><strong>Meaningful Visual Frames:</strong> {results.visualMetadataQuality.meaningfulFrameCount ?? 0} of {results.visualMetadataQuality.frameCount ?? 0}</p>
            )}
            <p><strong>Keyframes With Vision Signals:</strong> {results.visionSignalFrameCount ?? 0}</p>
            <p><strong>Temporal Instability:</strong> {typeof results.temporalInstabilityScore === "number" ? `${Math.round(results.temporalInstabilityScore * 100)}%` : "N/A"}</p>
            <p><strong>AI Visual Risk:</strong> {typeof results.aiVisualRiskScore === "number" ? `${Math.round(results.aiVisualRiskScore * 100)}%` : "N/A"}</p>
            <p><strong>Event Authenticity Risk:</strong> {typeof results.visualEventSummary?.authenticityRiskScore === "number" ? `${Math.round(results.visualEventSummary.authenticityRiskScore * 100)}%` : "N/A"}</p>
            <p><strong>Event-Window Consistency Risk:</strong> {typeof results.eventWindowConsistency?.overallTemporalAuthenticityRisk === "number" ? `${Math.round(results.eventWindowConsistency.overallTemporalAuthenticityRisk * 100)}%` : "N/A"}</p>
            <p><strong>Subject Reaction Risk:</strong> {typeof results.eventWindowConsistency?.subjectReactionRisk === "number" ? `${Math.round(results.eventWindowConsistency.subjectReactionRisk * 100)}%` : "N/A"}</p>
            <p><strong>Lighting Continuity Risk:</strong> {typeof results.eventWindowConsistency?.lightingContinuityRisk === "number" ? `${Math.round(results.eventWindowConsistency.lightingContinuityRisk * 100)}%` : "N/A"}</p>
            <p><strong>Debris/Motion Risk:</strong> {typeof results.eventWindowConsistency?.debrisMotionRisk === "number" ? `${Math.round(results.eventWindowConsistency.debrisMotionRisk * 100)}%` : "N/A"}</p>
            <p><strong>Event-Window Risk Signals:</strong> {(results.eventWindowConsistency?.riskSignals || []).join(", ") || "None"}</p>
            {results.eventWindowConsistency?.rationale && (
              <p><strong>Event-Window Rationale:</strong> {results.eventWindowConsistency.rationale}</p>
            )}
            <p><strong>Authenticity Risk Signals:</strong> {(results.visualEventSummary?.authenticityRiskSignals || results.visualEventSummary?.authenticitySignals || []).join(", ") || "None"}</p>
            <p><strong>Realism Signals:</strong> {(results.visualEventSummary?.authenticityRealismSignals || []).join(", ") || "None"}</p>
            {(results.visualEventSummary?.authenticityRationales || []).map((rationale, index) => (
              <p key={`authenticity-rationale-${index}`}><strong>Authenticity Note {index + 1}:</strong> {rationale}</p>
            ))}
            <p><strong>Object Disappearance Risk:</strong> {typeof results.objectDisappearanceRisk === "number" ? `${Math.round(results.objectDisappearanceRisk * 100)}%` : "N/A"}</p>
            <p><strong>Temporal Risk Signals:</strong> {(results.temporalRiskSignals || []).join(", ") || "None"}</p>
            <p><strong>Cross-Modal Hints:</strong> {results.crossModalHintCount ?? 0}</p>
            <p><strong>Scene Threshold:</strong> {results.keyframeSceneThreshold ?? 0.35}</p>
            {results.transcriptText && (
              <p><strong>Transcript Preview:</strong> {results.transcriptText.slice(0, 280)}</p>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
