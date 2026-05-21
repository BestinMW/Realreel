import fs from "fs";
import path from "path";

import { crossModalHints, SCHEMA_VERSION } from "./indicators";
import { createOcrProvider } from "./ocr";
import { analyzeFrameWithGemini } from "./vision";

const OCR_INIT_TIMEOUT_MS = Number(process.env.TESSERACT_INIT_TIMEOUT_MS || 15000);
const OCR_CLOSE_TIMEOUT_MS = Number(process.env.TESSERACT_CLOSE_TIMEOUT_MS || 3000);

export async function analyzeKeyframes({
  keyframePaths,
  keyframeTimestamps,
  outputPath,
  onProgress,
}) {
  onProgress?.({
    index: 0,
    total: keyframePaths.length,
    frame: "Initializing OCR",
  });
  const ocrProvider = await getOcrProvider();
  const frames = [];

  try {
    for (let index = 0; index < keyframePaths.length; index += 1) {
      const framePath = keyframePaths[index];
      const frame = path.basename(framePath);
      const timestampSeconds = keyframeTimestamps[index] ?? null;

      onProgress?.({
        index: index + 1,
        total: keyframePaths.length,
        frame,
      });

      const ocr = await ocrProvider.analyzeFrame(framePath);
      const ocrSummary = formatOcrSummary(ocr);
      const vision = await analyzeFrameWithGemini(framePath, { ocrSummary });

      const frameRecord = {
        frame,
        timestamp:
          timestampSeconds === null ? null : secondsToTimestamp(timestampSeconds),
        timestampSeconds,
        ocr: {
          ok: ocr.ok,
          text: ocr.text,
          indicators: ocr.indicators,
          confidence: ocr.confidence,
          error: ocr.error,
        },
        vision: {
          ok: vision.ok,
          indicators: vision.indicators,
          error: vision.error,
        },
        hints: crossModalHints(
          { indicators: ocr.indicators },
          { indicators: vision.indicators },
        ),
      };

      frames.push(frameRecord);
    }
  } finally {
    await withTimeout(
      ocrProvider.close(),
      OCR_CLOSE_TIMEOUT_MS,
      "Timed out while closing OCR provider.",
    ).catch(() => {});
  }

  const result = {
    schemaVersion: SCHEMA_VERSION,
    generatedAt: new Date().toISOString(),
    providerVersions: {
      ocr: "tesseract.js",
      vision: process.env.GEMINI_VISION_MODEL || "gemini-2.5-flash-lite",
    },
    frameCount: frames.length,
    frames,
  };

  await fs.promises.writeFile(outputPath, JSON.stringify(result, null, 2), "utf-8");
  return result;
}

async function getOcrProvider() {
  try {
    return await withTimeout(
      createOcrProvider(),
      OCR_INIT_TIMEOUT_MS,
      `Tesseract OCR initialization timed out after ${OCR_INIT_TIMEOUT_MS} ms.`,
    );
  } catch (error) {
    const message = error?.message || "OCR provider failed to initialize.";

    return {
      async analyzeFrame() {
        return {
          ok: false,
          text: { raw: "", lines: [], wordCount: 0 },
          indicators: {
            hasText: false,
            lineCount: 0,
            textAreaRatio: 0,
            likelyHeadline: false,
            hasNumbers: false,
            hasUrl: false,
            hasDateLike: false,
            hasAllCapsWords: false,
            avgLineConfidence: null,
          },
          confidence: null,
          error: message,
        };
      },

      async close() {},
    };
  }
}

function formatOcrSummary(ocr) {
  if (!ocr?.indicators) {
    return "hasText=false";
  }

  return [
    `hasText=${ocr.indicators.hasText}`,
    `lineCount=${ocr.indicators.lineCount}`,
    `likelyHeadline=${ocr.indicators.likelyHeadline}`,
  ].join(", ");
}

function withTimeout(promise, timeoutMs, message) {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]);
}

function secondsToTimestamp(seconds) {
  const safeSeconds = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(safeSeconds / 3600);
  const minutes = Math.floor((safeSeconds % 3600) / 60);
  const wholeSeconds = Math.floor(safeSeconds % 60);
  const milliseconds = Math.round((safeSeconds - Math.floor(safeSeconds)) * 1000);

  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(wholeSeconds).padStart(2, "0")}.${String(milliseconds).padStart(3, "0")}`;
}
