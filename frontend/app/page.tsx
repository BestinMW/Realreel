"use client";

import { useMemo, useState } from "react";

type PreviewSource =
  | { type: "empty" }
  | { type: "invalid" }
  | { type: "social"; platform: string }
  | { type: "video"; src: string }
  | { type: "iframe"; src: string; title: string };

type ProcessingResult = {
  success: boolean;
  rawVideoPath?: string;
  audioPath?: string;
  transcriptPath?: string;
  keyframeAnalysisPath?: string;
  claimAnalysisPath?: string;
  claimAnalysisOk?: boolean;
  claim?: string | null;
  claimVerdict?: string;
  claimConfidence?: number | null;
  misleadingProbability?: number | null;
  misleadingProbabilityRationale?: string;
  claimSummary?: string;
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

    if (url.hostname.includes("youtube.com")) {
      const videoId = url.searchParams.get("v");

      if (videoId) {
        return {
          type: "iframe",
          src: `https://www.youtube.com/embed/${videoId}`,
          title: "YouTube video preview",
        };
      }
    }

    if (url.hostname === "youtu.be") {
      const videoId = url.pathname.replace("/", "");

      if (videoId) {
        return {
          type: "iframe",
          src: `https://www.youtube.com/embed/${videoId}`,
          title: "YouTube video preview",
        };
      }
    }

    if (url.hostname.includes("vimeo.com")) {
      const videoId = url.pathname.split("/").filter(Boolean).at(-1);

      if (videoId) {
        return {
          type: "iframe",
          src: `https://player.vimeo.com/video/${videoId}`,
          title: "Vimeo video preview",
        };
      }
    }

    if (url.hostname.includes("tiktok.com")) {
      return { type: "social", platform: "TikTok" };
    }

    if (url.hostname.includes("instagram.com")) {
      return { type: "social", platform: "Instagram" };
    }

    return { type: "video", src: url.href };
  } catch {
    return { type: "invalid" };
  }
}

export default function Home() {
  const [videoUrl, setVideoUrl] = useState("");
  const preview = useMemo(() => getPreviewSource(videoUrl), [videoUrl]);

  const [isProcessing, setIsProcessing] = useState(false);
  const [results, setResults] = useState<ProcessingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressStage, setProgressStage] = useState("");

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
        body: JSON.stringify({ videoUrl }),
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
          <button onClick={handleProcessClick} disabled={isProcessing || preview.type === 'empty' || preview.type === 'invalid'}>
            {isProcessing ? 'Processing...' : 'Process Video'}
          </button>
        </div>
      </section>

      <section className="previewCard" aria-live="polite">
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
            <p><strong>Raw Video Path:</strong> {results.rawVideoPath}</p>
            <p><strong>Audio Path:</strong> {results.audioPath}</p>
            <p><strong>Transcript Path:</strong> {results.transcriptPath}</p>
            <p><strong>Keyframe Analysis Path:</strong> {results.keyframeAnalysisPath}</p>
            <p><strong>Claim Analysis Path:</strong> {results.claimAnalysisPath}</p>
            <p><strong>Claim:</strong> {results.claim || "No clear factual claim detected"}</p>
            <p><strong>Claim Verdict:</strong> {results.claimVerdict || "unverified"}</p>
            <p><strong>Claim Confidence:</strong> {typeof results.claimConfidence === "number" ? `${Math.round(results.claimConfidence * 100)}%` : "N/A"}</p>
            <p><strong>Misleading Chance:</strong> {typeof results.misleadingProbability === "number" ? `${Math.round(results.misleadingProbability * 100)}%` : "N/A"}</p>
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
            <p><strong>Keyframes With Vision Signals:</strong> {results.visionSignalFrameCount ?? 0}</p>
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
