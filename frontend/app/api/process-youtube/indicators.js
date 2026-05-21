export const SCHEMA_VERSION = "1";

// Year: 1900–2099. Also month names and numeric dates (e.g. 3/15/1998, 15-03-24).
const DATE_LIKE_PATTERN =
  /\b(?:(?:19|20)\d{2}|\d{1,2}[\/\-\.]\d{1,2}(?:[\/\-\.]\d{2,4})?|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b/i;

export const VISION_PROMPT = `Extract preprocessing indicators from this video keyframe.
Return ONLY JSON matching this schema. No markdown.
Do NOT transcribe text (OCR handles text). If you see text, only set hasTextOverlay true.
Do NOT conclude the video is misleading or fake; only list observable signals.

{
  "medium": "live_action|animation|screen_recording|mixed|unknown",
  "hasTextOverlay": boolean,
  "hasNewsStyleGraphics": boolean,
  "hasChartOrGraph": boolean,
  "hasSocialMediaUI": boolean,
  "appearsScreenshot": boolean,
  "peopleCount": "none|one|few|many|unknown",
  "faceVisible": boolean,
  "synthetic": {
    "aiLikelihood": "low|medium|high|unknown",
    "signals": ["watermark_visible|unnatural_face|warped_text|inconsistent_lighting|cgi_artifacts|none"]
  },
  "contextSignals": [
    { "type": "stock_broll|urgent_overlay_on_calm_scene|chart_no_source|stale_looking_footage|possible_deepfake|other", "confidence": "low|medium|high" }
  ],
  "visibleClaimHint": string or null,
  "confidence": number
}`;

const MEDIUM_VALUES = new Set([
  "live_action",
  "animation",
  "screen_recording",
  "mixed",
  "unknown",
]);

const PEOPLE_COUNT_VALUES = new Set(["none", "one", "few", "many", "unknown"]);

const AI_LIKELIHOOD_VALUES = new Set(["low", "medium", "high", "unknown"]);

const SYNTHETIC_SIGNAL_VALUES = new Set([
  "watermark_visible",
  "unnatural_face",
  "warped_text",
  "inconsistent_lighting",
  "cgi_artifacts",
  "none",
]);

const CONTEXT_SIGNAL_TYPES = new Set([
  "stock_broll",
  "urgent_overlay_on_calm_scene",
  "chart_no_source",
  "stale_looking_footage",
  "possible_deepfake",
  "other",
]);

const CONFIDENCE_LEVELS = new Set(["low", "medium", "high"]);

export const DEFAULT_VISION_INDICATORS = {
  medium: "unknown",
  hasTextOverlay: false,
  hasNewsStyleGraphics: false,
  hasChartOrGraph: false,
  hasSocialMediaUI: false,
  appearsScreenshot: false,
  peopleCount: "unknown",
  faceVisible: false,
  synthetic: { aiLikelihood: "unknown", signals: [] },
  contextSignals: [],
  visibleClaimHint: null,
  confidence: null,
};

export function deriveOcrIndicators({ lines, raw, width = 1, height = 1 }) {
  const hasText = lines.length > 0 || raw.length > 0;
  const joined = raw || lines.map((line) => line.text).join(" ");
  const topLines = lines.filter((line) => (line.boundingBox?.y0 ?? height) < height * 0.35);
  const textArea = lines.reduce((sum, line) => sum + bboxArea(line.boundingBox), 0);
  const imageArea = Math.max(width * height, 1);

  return {
    hasText,
    lineCount: lines.length,
    textAreaRatio: Math.min(1, Number((textArea / imageArea).toFixed(4))),
    likelyHeadline:
      topLines.length > 0 &&
      topLines.length <= 2 &&
      topLines.some((line) => line.text.length > 8),
    hasNumbers: /\d/.test(joined),
    hasUrl: /https?:\/\/|www\./i.test(joined),
    hasDateLike: DATE_LIKE_PATTERN.test(joined),
    hasAllCapsWords: /\b[A-Z]{4,}\b/.test(joined),
    avgLineConfidence:
      lines.length > 0
        ? Number(
            (lines.reduce((sum, line) => sum + line.confidence, 0) / lines.length).toFixed(2),
          )
        : null,
  };
}

export function estimateImageSizeFromLines(lines) {
  let width = 0;
  let height = 0;

  for (const line of lines) {
    const box = line.boundingBox;
    if (!box) {
      continue;
    }

    width = Math.max(width, box.x1);
    height = Math.max(height, box.y1);
  }

  return {
    width: width || 1,
    height: height || 1,
  };
}

export function normalizeVisionIndicators(parsed) {
  if (!parsed || typeof parsed !== "object") {
    return { ...DEFAULT_VISION_INDICATORS, synthetic: { ...DEFAULT_VISION_INDICATORS.synthetic } };
  }

  const synthetic = parsed.synthetic && typeof parsed.synthetic === "object" ? parsed.synthetic : {};
  const rawSignals = Array.isArray(synthetic.signals) ? synthetic.signals : [];
  const signals = rawSignals
    .filter((signal) => SYNTHETIC_SIGNAL_VALUES.has(signal) && signal !== "none")
    .slice(0, 8);

  const contextSignals = (Array.isArray(parsed.contextSignals) ? parsed.contextSignals : [])
    .map((entry) => normalizeContextSignal(entry))
    .filter(Boolean)
    .slice(0, 6);

  const visibleClaimHint =
    typeof parsed.visibleClaimHint === "string" && parsed.visibleClaimHint.trim()
      ? parsed.visibleClaimHint.trim().slice(0, 200)
      : null;

  return {
    medium: MEDIUM_VALUES.has(parsed.medium) ? parsed.medium : "unknown",
    hasTextOverlay: Boolean(parsed.hasTextOverlay),
    hasNewsStyleGraphics: Boolean(parsed.hasNewsStyleGraphics),
    hasChartOrGraph: Boolean(parsed.hasChartOrGraph),
    hasSocialMediaUI: Boolean(parsed.hasSocialMediaUI),
    appearsScreenshot: Boolean(parsed.appearsScreenshot),
    peopleCount: PEOPLE_COUNT_VALUES.has(parsed.peopleCount)
      ? parsed.peopleCount
      : "unknown",
    faceVisible: Boolean(parsed.faceVisible),
    synthetic: {
      aiLikelihood: AI_LIKELIHOOD_VALUES.has(synthetic.aiLikelihood)
        ? synthetic.aiLikelihood
        : "unknown",
      signals,
    },
    contextSignals,
    visibleClaimHint,
    confidence:
      typeof parsed.confidence === "number" && Number.isFinite(parsed.confidence)
        ? Math.max(0, Math.min(1, parsed.confidence))
        : null,
  };
}

export function crossModalHints(ocr, vision) {
  const hints = [];

  if (!ocr?.indicators || !vision?.indicators) {
    return hints;
  }

  if (ocr.indicators.hasText && !vision.indicators.hasTextOverlay) {
    hints.push({
      type: "ocr_vision_text_disagreement",
      confidence: "low",
    });
  }

  if (ocr.indicators.likelyHeadline && vision.indicators.medium === "live_action") {
    hints.push({
      type: "headline_over_footage_candidate",
      confidence: "medium",
    });
  }

  if (ocr.indicators.hasUrl && !vision.indicators.hasSocialMediaUI) {
    hints.push({
      type: "url_in_ocr_without_social_ui",
      confidence: "low",
    });
  }

  if (
    vision.indicators.synthetic.aiLikelihood === "high" &&
    vision.indicators.synthetic.signals.length > 0
  ) {
    hints.push({
      type: "synthetic_visual_signals",
      confidence: "medium",
    });
  }

  return hints;
}

function normalizeContextSignal(entry) {
  if (!entry || typeof entry !== "object") {
    return null;
  }

  const type = CONTEXT_SIGNAL_TYPES.has(entry.type) ? entry.type : "other";
  const confidence = CONFIDENCE_LEVELS.has(entry.confidence) ? entry.confidence : "low";

  return { type, confidence };
}

function bboxArea(box) {
  if (!box) {
    return 0;
  }

  return Math.max(0, box.x1 - box.x0) * Math.max(0, box.y1 - box.y0);
}
