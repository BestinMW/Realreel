import { createWorker, PSM } from "tesseract.js";
import path from "path";

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

function collectWords(blocks) {
  const words = [];

  for (const block of blocks || []) {
    for (const paragraph of block.paragraphs || []) {
      for (const line of paragraph.lines || []) {
        for (const word of line.words || []) {
          const text = word.text?.trim();
          if (!text || word.confidence < MIN_WORD_CONFIDENCE) {
            continue;
          }

          words.push({
            text,
            confidence: word.confidence,
            boundingBox: normalizeBox(word.bbox),
          });
        }
      }
    }
  }

  return words;
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
        const words = collectWords(result.data.blocks);

        return {
          ok: true,
          rawText: result.data.text?.trim() || "",
          confidence: result.data.confidence ?? null,
          words,
          error: null,
        };
      } catch (error) {
        return {
          ok: false,
          rawText: "",
          confidence: null,
          words: [],
          error: error?.message || "OCR failed.",
        };
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

function withTimeout(promise, timeoutMs, message) {
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]);
}
