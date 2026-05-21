import { createWorker, PSM } from "tesseract.js";
import path from "path";

import { deriveOcrIndicators, estimateImageSizeFromLines } from "./indicators";

const OCR_LANGUAGE = process.env.TESSERACT_LANGUAGE || "eng";
const MIN_WORD_CONFIDENCE = Number(process.env.TESSERACT_MIN_CONFIDENCE || 35);
const OCR_ENABLED = process.env.ENABLE_KEYFRAME_OCR !== "false";
const OCR_RECOGNITION_TIMEOUT_MS = Number(
  process.env.TESSERACT_RECOGNITION_TIMEOUT_MS || 8000,
);
const TESSERACT_ROOT = path.join(process.cwd(), "node_modules", "tesseract.js");
const TESSERACT_CORE_ROOT = path.join(
  process.cwd(),
  "node_modules",
  "tesseract.js-core",
);

function normalizeBox(box) {
  if (!box) {
    return null;
  }

  return {
    x0: box.x0,
    y0: box.y0,
    x1: box.x1,
    y1: box.y1,
  };
}

function collectLines(blocks) {
  const lines = [];

  for (const block of blocks || []) {
    for (const paragraph of block.paragraphs || []) {
      for (const line of paragraph.lines || []) {
        const text = line.text?.trim();
        if (!text || line.confidence < MIN_WORD_CONFIDENCE) {
          continue;
        }

        lines.push({
          text,
          confidence: line.confidence,
          boundingBox: normalizeBox(line.bbox),
        });
      }
    }
  }

  return lines;
}

function emptyOcrResult(error = null) {
  const lines = [];

  return {
    ok: !error,
    text: {
      raw: "",
      lines,
      wordCount: 0,
    },
    indicators: deriveOcrIndicators({ lines, raw: "" }),
    confidence: null,
    error,
  };
}

export async function createOcrProvider() {
  if (!OCR_ENABLED) {
    return disabledProvider("OCR disabled by ENABLE_KEYFRAME_OCR=false.");
  }

  const worker = await createWorker(OCR_LANGUAGE, 1, {
    workerPath: path.join(TESSERACT_ROOT, "src", "worker", "node", "index.js"),
    corePath: path.join(TESSERACT_CORE_ROOT, "tesseract-core-simd.wasm.js"),
  });
  await worker.setParameters({
    tessedit_pageseg_mode: PSM.SPARSE_TEXT,
  });

  return {
    async analyzeFrame(framePath) {
      try {
        const result = await withTimeout(
          worker.recognize(framePath),
          OCR_RECOGNITION_TIMEOUT_MS,
          `Tesseract OCR timed out after ${OCR_RECOGNITION_TIMEOUT_MS} ms.`,
        );
        const rawText = result.data.text?.trim() || "";
        const lines = collectLines(result.data.blocks);
        const { width, height } = estimateImageSizeFromLines(lines);
        const indicators = deriveOcrIndicators({
          lines,
          raw: rawText,
          width,
          height,
        });

        return {
          ok: true,
          text: {
            raw: rawText,
            lines,
            wordCount: lines.reduce(
              (count, line) => count + line.text.split(/\s+/).filter(Boolean).length,
              0,
            ),
          },
          indicators,
          confidence: result.data.confidence ?? null,
          error: null,
        };
      } catch (error) {
        return emptyOcrResult(error?.message || "OCR failed.");
      }
    },

    async close() {
      await worker.terminate();
    },
  };
}

function disabledProvider(message) {
  return {
    async analyzeFrame() {
      return emptyOcrResult(message);
    },

    async close() {},
  };
}

function withTimeout(promise, timeoutMs, message) {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]);
}
