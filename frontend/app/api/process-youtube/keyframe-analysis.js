import fs from "fs";
import path from "path";

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

      const [ocr, vision] = await Promise.all([
        ocrProvider.analyzeFrame(framePath),
        analyzeFrameWithGemini(framePath),
      ]);

      frames.push({
        frame,
        timestamp:
          timestampSeconds === null ? null : secondsToTimestamp(timestampSeconds),
        timestampSeconds,
        ocrText: ocr.words,
        rawDetectedText: ocr.rawText,
        ocrConfidence: ocr.confidence,
        ocrError: ocr.error,
        sceneDescription: vision.sceneDescription,
        objects: vision.objects,
        people: vision.people,
        setting: vision.setting,
        actions: vision.actions,
        notes: vision.notes,
        visionConfidence: vision.confidence,
        visionError: vision.error,
      });
    }
  } finally {
    await withTimeout(
      ocrProvider.close(),
      OCR_CLOSE_TIMEOUT_MS,
      "Timed out while closing OCR provider.",
    ).catch(() => {});
  }

  const result = {
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
          rawText: "",
          confidence: null,
          words: [],
          error: message,
        };
      },

      async close() {},
    };
  }
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
