import fs from "fs";

const GEMINI_MODEL = process.env.GEMINI_VISION_MODEL || "gemini-2.5-flash-lite";
const GEMINI_TIMEOUT_MS = Number(process.env.GEMINI_VISION_TIMEOUT_MS || 8000);
const VISION_ENABLED = process.env.ENABLE_KEYFRAME_VISION !== "false";

function getGeminiApiKey() {
  return process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
}

function emptyVisionResult(error = null) {
  return {
    ok: !error,
    sceneDescription: "",
    objects: [],
    people: [],
    setting: "",
    actions: [],
    notes: error || "No notable visual details returned.",
    confidence: null,
    error,
  };
}

function parseJsonResponse(text) {
  try {
    return JSON.parse(text);
  } catch {
    const match = text.match(/\{[\s\S]*\}/);
    return match ? JSON.parse(match[0]) : null;
  }
}

export async function analyzeFrameWithGemini(framePath) {
  if (!VISION_ENABLED) {
    return emptyVisionResult(
      "Gemini vision disabled by ENABLE_KEYFRAME_VISION=false.",
    );
  }

  const apiKey = getGeminiApiKey();

  if (!apiKey) {
    return emptyVisionResult(
      "Gemini vision is not configured. Add GEMINI_API_KEY to frontend/.env.local.",
    );
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), GEMINI_TIMEOUT_MS);

  try {
    const imageData = await fs.promises.readFile(framePath, "base64");
    const response = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${apiKey}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          contents: [
            {
              parts: [
                {
                  inline_data: {
                    mime_type: "image/jpeg",
                    data: imageData,
                  },
                },
                {
                  text:
                    "Analyze this video keyframe for a media forensics pipeline. " +
                    "Return only JSON with keys: sceneDescription, objects, people, setting, actions, notes, confidence. " +
                    "Keep sceneDescription short. Include uncertainty in notes. Do not do OCR; OCR is handled separately.",
                },
              ],
            },
          ],
          generationConfig: {
            responseMimeType: "application/json",
          },
        }),
      },
    );

    if (!response.ok) {
      const details = await response.text();
      return emptyVisionResult(`Gemini vision request failed: ${details}`);
    }

    const payload = await response.json();
    const text = payload.candidates?.[0]?.content?.parts?.[0]?.text || "";
    const parsed = parseJsonResponse(text);

    if (!parsed) {
      return emptyVisionResult("Gemini returned an unparseable vision response.");
    }

    return {
      ok: true,
      sceneDescription: parsed.sceneDescription || "",
      objects: Array.isArray(parsed.objects) ? parsed.objects : [],
      people: Array.isArray(parsed.people) ? parsed.people : [],
      setting: parsed.setting || "",
      actions: Array.isArray(parsed.actions) ? parsed.actions : [],
      notes: parsed.notes || "",
      confidence: parsed.confidence ?? null,
      error: null,
    };
  } catch (error) {
    if (error?.name === "AbortError") {
      return emptyVisionResult(
        `Gemini vision timed out after ${GEMINI_TIMEOUT_MS} ms.`,
      );
    }

    return emptyVisionResult(error?.message || "Gemini vision failed.");
  } finally {
    clearTimeout(timeout);
  }
}
