"use client";

import { useMemo, useState } from "react";

type PreviewSource =
  | { type: "empty" }
  | { type: "invalid" }
  | { type: "video"; src: string }
  | { type: "iframe"; src: string; title: string };

type ProcessingResult = {
  success: boolean;
  rawVideoPath?: string;
  audioPath?: string;
  frameCount?: number;
  frameRate?: number;
  message?: string;
}

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

  async function handleProcessClick() {
    setIsProcessing(true);
    setError(null);
    setResults(null);

    try {
      const response = await fetch('/api/process-youtube', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ youtubeUrl: videoUrl }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.message || 'Something went wrong during processing.');
      }

      setResults(data);
    } catch (err: any) {
      setError(err.message);
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
          Paste a direct video link or YouTube URL to load a preview, then
          click "Process" to extract audio and frames.
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

        {preview.type === "video" && (
          <video controls src={preview.src}>
            Your browser does not support the video tag.
          </video>
        )}
      </section>

      <section className="resultsCard" aria-live="polite">
        {isProcessing && (
          <div className="emptyState">
            <span>Processing video... please wait.</span>
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
            <p><strong>Frames Analyzed Locally:</strong> {results.frameCount ?? 0}</p>
            <p><strong>Frame Sampling:</strong> {results.frameRate ?? 1} frame per second</p>
          </div>
        )}
      </section>
    </main>
  );
}
