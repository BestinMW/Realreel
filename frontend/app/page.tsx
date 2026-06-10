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
  databaseVideoId?: string | null;
  externalId?: string | null;
  sourceUrl?: string | null;
  claim?: string | null;
  claimVerdict?: string;
  claimConfidence?: number | null;
  claimSummary?: string;
  depictedEvent?: string | null;
  misleadingProbability?: number | null;
  misleadingProbabilityRationale?: string;
  visualAuthenticityRisk?: number | null;
  visualAuthenticityRationale?: string;
  thumbnailClickbaitScore?: number | null;
  thumbnailSummary?: string;
  thumbnailClickbaitRationale?: string;
  thumbnailClickbaitMismatches?: string[];
  recommendedAction?: string;
  isRepost?: boolean;
  repostProbability?: number | null;
  repostRisk?: number | null;
  repostRationale?: string;
  repostMatches?: Array<Record<string, unknown>>;
};

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

function isValidUrl(input: string) {
  try {
    new URL(input.trim());
    return true;
  } catch {
    return false;
  }
}

function getReliabilityScore(result: ProcessingResult | null) {
  if (!result) {
    return null;
  }

  const misleadingRisk =
    typeof result.misleadingProbability === "number"
      ? result.misleadingProbability
      : null;
  const visualRisk =
    typeof result.visualAuthenticityRisk === "number"
      ? result.visualAuthenticityRisk
      : null;
  const thumbnailRisk =
    typeof result.thumbnailClickbaitScore === "number"
      ? result.thumbnailClickbaitScore
      : null;
  const repostRisk =
    typeof result.repostRisk === "number"
      ? result.repostRisk
      : null;
  const highestRisk = Math.max(
    misleadingRisk ?? 0,
    visualRisk ?? 0,
    thumbnailRisk ?? 0,
    repostRisk ?? 0,
  );

  if (
    misleadingRisk !== null ||
    visualRisk !== null ||
    thumbnailRisk !== null ||
    repostRisk !== null
  ) {
    return Math.max(0, Math.min(100, Math.round((1 - highestRisk) * 100)));
  }

  if (typeof result.claimConfidence === "number") {
    return Math.max(0, Math.min(100, Math.round(result.claimConfidence * 100)));
  }

  return null;
}

function getReliabilityExplanation(result: ProcessingResult | null) {
  if (!result) {
    return "";
  }

  const parts = [];
  const visualSubject = result.depictedEvent || result.claim;

  if (visualSubject) {
    parts.push(`The video appears to show ${visualSubject}.`);
  }

  if (result.claimSummary) {
    parts.push(result.claimSummary);
  }

  if (result.claimVerdict && result.claimVerdict !== "no_clear_claim") {
    const readableVerdict = result.claimVerdict.replaceAll("_", " ");
    parts.push(`The claim was rated ${readableVerdict}.`);
  }

  if (result.visualAuthenticityRationale) {
    parts.push(`Visual authenticity: ${result.visualAuthenticityRationale}`);
  }

  if (result.thumbnailSummary) {
    parts.push(`The thumbnail appears to show ${result.thumbnailSummary}.`);
  }

  if (result.thumbnailClickbaitRationale) {
    parts.push(`Thumbnail fit: ${result.thumbnailClickbaitRationale}`);
  }

  if (result.thumbnailClickbaitMismatches?.length) {
    parts.push(`Thumbnail mismatch: ${result.thumbnailClickbaitMismatches.join("; ")}.`);
  }

  if (result.misleadingProbabilityRationale) {
    parts.push(`Misleading context: ${result.misleadingProbabilityRationale}`);
  }

  if (typeof result.repostRisk === "number" && result.repostRationale) {
    parts.push(`Repost risk: ${result.repostRationale}`);
  }

  if (result.recommendedAction === "flag_for_review") {
    parts.push("Because of those issues, this video should be reviewed before being trusted or shared.");
  }

  if (parts.length > 0) {
    return parts.join(" ");
  }

  return "The analysis did not return enough detail to explain this score.";
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
  const [feedbackLabel, setFeedbackLabel] = useState<"Correct" | "Incorrect" | "">("");
  const [feedbackComment, setFeedbackComment] = useState("");
  const [feedbackMessage, setFeedbackMessage] = useState<string | null>(null);
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);

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

  const urlReady = videoUrl.trim().length > 0 && isValidUrl(videoUrl);
  const reliabilityScore = getReliabilityScore(results);
  const reliabilityExplanation = getReliabilityExplanation(results);

  async function handleProcessClick() {
    setIsProcessing(true);
    setError(null);
    setResults(null);
    setFeedbackLabel("");
    setFeedbackComment("");
    setFeedbackMessage(null);
    setProgress(0);
    setProgressStage("Starting");

    try {
      const response = await fetch("/api/process-youtube", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ videoUrl, fastProcessingMode }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.message || "Something went wrong during processing.");
      }

      if (!response.body) {
        throw new Error("The processing stream did not start.");
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

  function getFeedbackVidId() {
    if (!results) {
      return "";
    }
    return (
      results.databaseVideoId ||
      results.externalId ||
      results.sourceUrl ||
      videoUrl.trim()
    );
  }

  async function handleFeedbackSubmit() {
    const vidId = getFeedbackVidId();
    if (!vidId || !feedbackLabel) {
      setFeedbackMessage("empty feedback");
      return;
    }

    setIsSubmittingFeedback(true);
    setFeedbackMessage(null);

    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vid_id: vidId,
          label: feedbackLabel,
          comment: feedbackComment,
        }),
      });

      const data = await response.json().catch(() => null);
      const message = data?.message || "feedback to storage failure";
      setFeedbackMessage(message);

      if (data?.status === "success") {
        setFeedbackComment("");
      }
    } catch {
      setFeedbackMessage("feedback to storage failure");
    } finally {
      setIsSubmittingFeedback(false);
    }
  }

  return (
    <main className="userPage">
      <section className="userPanel" aria-live="polite">
        <div className="brandRow">
          <p className="eyebrow">RealReel</p>
        </div>

        <h1>Is it real?</h1>

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
            <button
              className="primaryButton"
              onClick={handleProcessClick}
              disabled={isProcessing || !urlReady}
            >
              {isProcessing ? "Processing..." : "Process Video"}
            </button>
          </div>
          {fastProcessingMode && (
            <p className="modeHint">
              Skips visual events, metadata, thumbnail clickbait, and raw video upload.
            </p>
          )}
        </div>

        <section
          className={`userPreview ${preview.type === "iframe" && preview.orientation === "portrait" ? "portraitPreview" : ""}`}
          aria-live="polite"
        >
          {preview.type === "empty" && (
            <div className="emptyState">
              <span>Paste a video link to preview it here.</span>
            </div>
          )}

          {preview.type === "invalid" && (
            <div className="emptyState error">
              <span>Please enter a full video URL, including https://.</span>
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
              <span>{preview.platform} link ready to process. Preview is limited for this URL format.</span>
            </div>
          )}

          {preview.type === "video" && (
            <video controls src={preview.src}>
              Your browser does not support the video tag.
            </video>
          )}
        </section>

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
          <div className="scorePanel errorPanel">
            <span>Error</span>
            <strong>{error}</strong>
          </div>
        )}

        {results?.success && (
          <>
            <div className="scorePanel">
              <span>Reliability Score</span>
              <strong>{reliabilityScore !== null ? `${reliabilityScore}%` : "N/A"}</strong>
              {reliabilityExplanation && <p>{reliabilityExplanation}</p>}
            </div>

            <section className="feedbackPanel">
              <span>Was this analysis correct?</span>
              <div className="feedbackChoices">
                <label className="feedbackChoice">
                  <input
                    type="radio"
                    name="feedback-label"
                    value="Correct"
                    checked={feedbackLabel === "Correct"}
                    onChange={() => setFeedbackLabel("Correct")}
                    disabled={isSubmittingFeedback}
                  />
                  Correct
                </label>
                <label className="feedbackChoice">
                  <input
                    type="radio"
                    name="feedback-label"
                    value="Incorrect"
                    checked={feedbackLabel === "Incorrect"}
                    onChange={() => setFeedbackLabel("Incorrect")}
                    disabled={isSubmittingFeedback}
                  />
                  Incorrect
                </label>
              </div>
              <label className="feedbackCommentLabel" htmlFor="feedback-comment">
                Comment (optional)
              </label>
              <textarea
                id="feedback-comment"
                className="feedbackComment"
                value={feedbackComment}
                onChange={(event) => setFeedbackComment(event.target.value)}
                placeholder="Tell us what was wrong or right..."
                disabled={isSubmittingFeedback}
                rows={3}
              />
              <button
                type="button"
                className="primaryButton"
                onClick={handleFeedbackSubmit}
                disabled={isSubmittingFeedback || !feedbackLabel}
              >
                {isSubmittingFeedback ? "Submitting..." : "Submit Feedback"}
              </button>
              {feedbackMessage && (
                <p className={`feedbackMessage ${feedbackMessage === "feedback submitted" ? "feedbackSuccess" : "feedbackError"}`}>
                  {feedbackMessage}
                </p>
              )}
            </section>
          </>
        )}
      </section>
    </main>
  );
}
