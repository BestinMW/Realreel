import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

CLAIM_ANALYSIS_ENABLED = os.environ.get("ENABLE_CLAIM_ANALYSIS", "true").lower() != "false"
OPENAI_CLAIM_MODEL = os.environ.get("OPENAI_CLAIM_MODEL", "gpt-4.1-mini")
OPENAI_CLAIM_TIMEOUT_SECONDS = float(os.environ.get("OPENAI_CLAIM_TIMEOUT_SECONDS", "120"))


def analyze_claim(*, transcript: dict, keyframe_analysis: dict) -> dict:
    if not CLAIM_ANALYSIS_ENABLED:
        return _empty_result("Claim analysis disabled by ENABLE_CLAIM_ANALYSIS=false.")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return _empty_result("OpenAI claim analysis is not configured. Set OPENAI_API_KEY.")

    prompt = _build_prompt(transcript=transcript, keyframe_analysis=keyframe_analysis)

    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_CLAIM_MODEL,
                "tools": [{"type": "web_search", "external_web_access": True}],
                "tool_choice": "auto",
                "include": ["web_search_call.action.sources"],
                "input": prompt,
            },
            timeout=OPENAI_CLAIM_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return _empty_result(
            f"OpenAI claim analysis timed out after {OPENAI_CLAIM_TIMEOUT_SECONDS} seconds."
        )
    except Exception as exc:
        return _empty_result(str(exc))

    if response.status_code >= 400:
        return _empty_result(f"OpenAI claim analysis failed: {response.text}")

    payload = response.json()
    text = _extract_response_text(payload)
    parsed = _parse_json_response(text)

    if not parsed:
        return {
            **_empty_result("OpenAI returned an unparseable claim analysis response."),
            "rawResponseText": text,
        }

    normalized = _normalize_claim_analysis(parsed)
    normalized["ok"] = True
    normalized["error"] = None
    normalized["model"] = OPENAI_CLAIM_MODEL
    normalized["generatedAt"] = datetime.now(timezone.utc).isoformat()
    normalized["sources"] = _extract_sources(payload, normalized.get("sources", []))
    return normalized


def _build_prompt(*, transcript: dict, keyframe_analysis: dict) -> str:
    transcript_text = (transcript.get("text") or "").strip()
    frames = []

    for frame in (keyframe_analysis.get("frames") or [])[:8]:
        ocr = frame.get("ocr", {})
        vision = frame.get("vision", {})
        indicators = vision.get("indicators", {})
        visible_text = indicators.get("visibleText") or []
        frames.append(
            {
                "frame": frame.get("frame"),
                "timestamp": frame.get("timestamp"),
                "ocrText": ocr.get("text", {}).get("raw", ""),
                "geminiVisibleText": visible_text,
                "visibleClaimHint": indicators.get("visibleClaimHint"),
                "medium": indicators.get("medium"),
                "contextSignals": indicators.get("contextSignals", []),
            }
        )

    return f"""
You are a careful fact-checking assistant for a video analysis pipeline.

Task:
1. Identify the main factual claim or claims made by this video from the transcript and visual metadata.
2. Use web search to verify the claim against reliable sources.
3. Return ONLY valid JSON. Do not use markdown.
4. If the video does not make a clear factual claim, say so and do not overstate.
5. Do not claim something is true or false unless the provided evidence supports it.
6. Estimate misleadingProbability as the chance a normal viewer could be misled by the video's claim or presentation, where 0.0 means very unlikely misleading and 1.0 means very likely misleading. This is a viewer-risk probability, not a measurement of the creator's intent.
7. Do not set misleadingProbability to 0.0 just because the source is satire or parody. Satire can lower the risk if it is obvious from the video itself, but a confidently false factual claim should still have meaningful misleading risk.

Output schema:
{{
  "claim": "main claim being checked, or null",
  "claimType": "event|health|politics|science|finance|identity|location|satire_or_parody|other|none",
  "verdict": "true|mostly_true|mixed|mostly_false|false|unverified|no_clear_claim",
  "confidence": 0.0,
  "misleadingProbability": 0.0,
  "misleadingProbabilityRationale": "why this risk score was chosen",
  "summary": "short explanation",
  "evidence": [
    {{
      "sourceTitle": "source title",
      "url": "https://...",
      "supports": "supports|contradicts|context|unclear",
      "note": "how this source relates to the claim"
    }}
  ],
  "missingContext": ["important caveats or unknowns"],
  "videoSignalsUsed": ["transcript", "visible text", "scene context"],
  "recommendedAction": "accept|flag_for_review|needs_more_evidence"
}}

Video transcript:
{transcript_text[:12000]}

Keyframe metadata:
{json.dumps(frames, ensure_ascii=False)[:12000]}
""".strip()


def _extract_response_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]

    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip()


def _parse_json_response(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def _normalize_claim_analysis(parsed: dict) -> dict:
    verdicts = {
        "true",
        "mostly_true",
        "mixed",
        "mostly_false",
        "false",
        "unverified",
        "no_clear_claim",
    }
    claim_types = {
        "event",
        "health",
        "politics",
        "science",
        "finance",
        "identity",
        "location",
        "satire_or_parody",
        "other",
        "none",
    }

    confidence = parsed.get("confidence")
    if isinstance(confidence, (int, float)):
        confidence = max(0.0, min(1.0, float(confidence)))
    else:
        confidence = None

    verdict = parsed.get("verdict") if parsed.get("verdict") in verdicts else "unverified"
    claim_type = parsed.get("claimType") if parsed.get("claimType") in claim_types else "other"

    misleading_probability = parsed.get("misleadingProbability")
    if isinstance(misleading_probability, (int, float)):
        misleading_probability = max(0.0, min(1.0, float(misleading_probability)))
    else:
        misleading_probability = _estimate_misleading_probability(
            verdict=verdict,
            confidence=confidence,
        )
    misleading_probability = _apply_misleading_probability_floor(
        probability=misleading_probability,
        verdict=verdict,
        claim_type=claim_type,
    )

    evidence = parsed.get("evidence") if isinstance(parsed.get("evidence"), list) else []
    normalized_evidence = []
    for item in evidence[:10]:
        if not isinstance(item, dict):
            continue
        normalized_evidence.append(
            {
                "sourceTitle": str(item.get("sourceTitle") or "").strip()[:200],
                "url": str(item.get("url") or "").strip()[:500],
                "supports": item.get("supports")
                if item.get("supports") in {"supports", "contradicts", "context", "unclear"}
                else "unclear",
                "note": str(item.get("note") or "").strip()[:500],
            }
        )

    return {
        "schemaVersion": "1",
        "claim": parsed.get("claim") if isinstance(parsed.get("claim"), str) else None,
        "claimType": claim_type,
        "verdict": verdict,
        "confidence": confidence,
        "misleadingProbability": misleading_probability,
        "misleadingProbabilityRationale": str(
            parsed.get("misleadingProbabilityRationale") or ""
        ).strip()[:800],
        "summary": str(parsed.get("summary") or "").strip()[:1200],
        "evidence": normalized_evidence,
        "missingContext": _string_list(parsed.get("missingContext"), limit=8),
        "videoSignalsUsed": _string_list(parsed.get("videoSignalsUsed"), limit=8),
        "recommendedAction": parsed.get("recommendedAction")
        if parsed.get("recommendedAction")
        in {"accept", "flag_for_review", "needs_more_evidence"}
        else "needs_more_evidence",
    }


def _estimate_misleading_probability(*, verdict: Any, confidence: float | None) -> float | None:
    base_by_verdict = {
        "true": 0.05,
        "mostly_true": 0.2,
        "mixed": 0.5,
        "mostly_false": 0.75,
        "false": 0.9,
        "unverified": 0.55,
        "no_clear_claim": 0.1,
    }
    if verdict not in base_by_verdict:
        return None

    base = base_by_verdict[verdict]
    if confidence is None:
        return base

    if verdict in {"true", "mostly_true", "no_clear_claim"}:
        return round(base * confidence + 0.35 * (1 - confidence), 4)
    if verdict in {"mostly_false", "false"}:
        return round(base * confidence + 0.55 * (1 - confidence), 4)
    return round(base, 4)


def _apply_misleading_probability_floor(
    *,
    probability: float | None,
    verdict: Any,
    claim_type: Any,
) -> float | None:
    if probability is None:
        return None

    floors = {
        "false": 0.7,
        "mostly_false": 0.55,
        "mixed": 0.35,
        "unverified": 0.25,
    }
    floor = floors.get(verdict)
    if floor is None:
        return probability

    if claim_type == "satire_or_parody":
        floor = min(floor, 0.35)

    return round(max(probability, floor), 4)


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:300] for item in value[:limit] if str(item).strip()]


def _extract_sources(payload: dict, model_sources: list[dict]) -> list[dict]:
    sources = list(model_sources)
    seen = {source.get("url") for source in sources if source.get("url")}

    for source in payload.get("sources", []) or []:
        url = source.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append(
            {
                "sourceTitle": source.get("title") or "",
                "url": url,
                "supports": "context",
                "note": "Source returned by web search.",
            }
        )

    for item in payload.get("output", []) or []:
        action = item.get("action") or {}
        for source in action.get("sources", []) or []:
            url = source.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append(
                {
                    "sourceTitle": source.get("title") or "",
                    "url": url,
                    "supports": "context",
                    "note": "Source returned by web search.",
                }
            )

        for content in item.get("content", []) or []:
            for annotation in content.get("annotations", []) or []:
                url = annotation.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                sources.append(
                    {
                        "sourceTitle": annotation.get("title") or "",
                        "url": url,
                        "supports": "context",
                        "note": "Source returned by web search.",
                    }
                )

    return sources[:10]


def _empty_result(error: str) -> dict:
    return {
        "schemaVersion": "1",
        "ok": False,
        "error": error,
        "model": OPENAI_CLAIM_MODEL,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "claim": None,
        "claimType": "none",
        "verdict": "unverified",
        "confidence": None,
        "misleadingProbability": None,
        "misleadingProbabilityRationale": "",
        "summary": "",
        "evidence": [],
        "sources": [],
        "missingContext": [],
        "videoSignalsUsed": [],
        "recommendedAction": "needs_more_evidence",
    }
