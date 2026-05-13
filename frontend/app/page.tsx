"use client";

import { useMemo, useState } from "react";

type PreviewSource =
  | { type: "empty" }
  | { type: "invalid" }
  | { type: "video"; src: string }
  | { type: "iframe"; src: string; title: string };

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

  return (
    <main className="page">
      <section className="hero">
        <p className="eyebrow">RealReel</p>
        <h1>Preview any video URL in one place.</h1>
        <p className="intro">
          Paste a direct video link, YouTube URL, or Vimeo URL to load a quick
          preview.
        </p>

        <label className="inputGroup" htmlFor="video-url">
          Video URL
          <input
            id="video-url"
            type="url"
            value={videoUrl}
            onChange={(event) => setVideoUrl(event.target.value)}
            placeholder="https://example.com/video.mp4"
          />
        </label>
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
    </main>
  );
}
