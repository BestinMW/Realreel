import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

CLAIM_ANALYSIS_ENABLED = os.environ.get("ENABLE_CLAIM_ANALYSIS", "true").lower() != "false"
OPENAI_CLAIM_MODEL = os.environ.get("OPENAI_CLAIM_MODEL", "gpt-4.1-mini")
OPENAI_CLAIM_TIMEOUT_SECONDS = float(os.environ.get("OPENAI_CLAIM_TIMEOUT_SECONDS", "120"))


def analyze_claim(
    *,
    transcript: dict,
    keyframe_analysis: dict,
    temporal_analysis: dict | None = None,
    visual_event_analysis: dict | None = None,
) -> dict:
    if not CLAIM_ANALYSIS_ENABLED:
        return _empty_result("Claim analysis disabled by ENABLE_CLAIM_ANALYSIS=false.")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return _empty_result("OpenAI claim analysis is not configured. Set OPENAI_API_KEY.")

    prompt = _build_prompt(
        transcript=transcript,
        keyframe_analysis=keyframe_analysis,
        temporal_analysis=temporal_analysis,
        visual_event_analysis=visual_event_analysis,
    )

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
    visual_risk = _estimate_visual_authenticity_risk(
        keyframe_analysis=keyframe_analysis,
        temporal_analysis=temporal_analysis,
        visual_event_analysis=visual_event_analysis,
        parsed=parsed,
    )
    normalized["visualAuthenticityRisk"] = visual_risk["visualAuthenticityRisk"]
    normalized["visualAuthenticityRationale"] = visual_risk[
        "visualAuthenticityRationale"
    ]
    normalized["visualAuthenticitySignals"] = visual_risk["visualAuthenticitySignals"]
    if not normalized.get("depictedEvent"):
        normalized["depictedEvent"] = visual_risk["depictedEvent"]
    normalized["misleadingProbability"] = _merge_visual_risk_into_misleading_probability(
        misleading_probability=normalized.get("misleadingProbability"),
        visual_authenticity_risk=visual_risk["visualAuthenticityRisk"],
        verdict=normalized.get("verdict"),
        depicted_event=visual_risk["depictedEvent"],
    )
    normalized = _apply_visual_event_fallback(
        normalized,
        keyframe_analysis=keyframe_analysis,
        visual_event_analysis=visual_event_analysis,
    )
    normalized = _remove_unsupported_web_specifics(
        normalized,
        transcript=transcript,
        keyframe_analysis=keyframe_analysis,
        visual_event_analysis=visual_event_analysis,
    )
    normalized = _apply_visual_authenticity_guardrails(normalized)
    normalized["ok"] = True
    normalized["error"] = None
    normalized["model"] = OPENAI_CLAIM_MODEL
    normalized["generatedAt"] = datetime.now(timezone.utc).isoformat()
    normalized["sources"] = _extract_sources(payload, normalized.get("sources", []))
    return normalized


def _build_prompt(
    *,
    transcript: dict,
    keyframe_analysis: dict,
    temporal_analysis: dict | None = None,
    visual_event_analysis: dict | None = None,
) -> str:
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
                "sceneDescription": indicators.get("sceneDescription"),
                "notableObjects": indicators.get("notableObjects", []),
                "notableActions": indicators.get("notableActions", []),
                "destructiveEvent": indicators.get("destructiveEvent"),
                "synthetic": indicators.get("synthetic"),
                "visibleClaimHint": indicators.get("visibleClaimHint"),
                "medium": indicators.get("medium"),
                "contextSignals": indicators.get("contextSignals", []),
            }
        )

    temporal_summary = (temporal_analysis or {}).get("summary") or {}
    temporal_packet = {
        "summary": temporal_summary,
        "comparisonExamples": (temporal_analysis or {}).get("comparisons", [])[:6],
    }
    visual_event_packet = {
        "summary": (visual_event_analysis or {}).get("summary") or {},
        "frames": [
            {
                "frame": frame.get("frame"),
                "timestamp": frame.get("timestamp"),
                "sceneDescription": (
                    frame.get("vision", {})
                    .get("indicators", {})
                    .get("sceneDescription")
                ),
                "destructiveEvent": (
                    frame.get("vision", {})
                    .get("indicators", {})
                    .get("destructiveEvent")
                ),
                "synthetic": (
                    frame.get("vision", {})
                    .get("indicators", {})
                    .get("synthetic")
                ),
                "notableActions": (
                    frame.get("vision", {})
                    .get("indicators", {})
                    .get("notableActions", [])
                ),
            }
            for frame in (visual_event_analysis or {}).get("frames", [])[:8]
        ],
    }

    return f"""
You are a careful fact-checking assistant for a video analysis pipeline.

Task:
1. Identify the main factual claim or claims made by this video from the transcript, visible text, and visual metadata.
2. Use web search to verify the claim against reliable sources.
3. Return ONLY valid JSON. Do not use markdown.
4. If the video has no explicit spoken or written claim but visually depicts a meaningful scene, action, object, person, place, or event, treat the visual presentation as an implied claim about what the footage shows. Summarize that in claim instead of returning null.
5. Do not claim something is true or false unless the provided evidence supports it.
6. Do NOT add a location, date, casualty count, named incident, cause, organization, or named person unless that exact detail appears in the transcript, visible text, or visual metadata. Web search results can verify or contextualize only details already present in the video metadata; they must not expand the video's claim into a different real-world incident.
7. If web search finds a similar-looking event but the video does not provide matching location/date/name clues, keep verdict unverified and mention the similar event only as evidence/context, not as the claim or summary of the video.
8. Estimate misleadingProbability as the chance a normal viewer could be misled by the video's claim or presentation, where 0.0 means very unlikely misleading and 1.0 means very likely misleading. This is a viewer-risk probability, not a measurement of the creator's intent.
9. Do not set misleadingProbability to 0.0 just because the source is satire or parody. Satire can lower the risk if it is obvious from the video itself, but a confidently false factual claim should still have meaningful misleading risk.
10. If there is no spoken/textual claim, still assess whether the visuals imply a real-world scene or event. A clip showing an action, unusual scene, public figure, location, disaster, product, medical/science demonstration, police/military activity, or other meaningful subject can still be misleading if it appears synthetic, staged, out of context, or presented without disclosure.
11. Distinguish claim fact-checking from visual authenticity. Use visualAuthenticityRisk for the chance that the depicted scene/event is AI-generated, manipulated, or not authentic footage of a real event.
12. Do not mark visual-only footage as accept/true solely because similar real footage or events exist. If the visual metadata reports medium/high synthetic likelihood, impossible physics, object disappearance, temporal instability, malformed details, or other authenticity concerns, raise visualAuthenticityRisk and set recommendedAction to flag_for_review unless reliable sources specifically verify this exact footage.

Output schema:
{{
  "claim": "main claim being checked, or null",
  "claimType": "event|health|politics|science|finance|identity|location|satire_or_parody|other|none",
  "verdict": "true|mostly_true|mixed|mostly_false|false|unverified|no_clear_claim",
  "confidence": 0.0,
  "misleadingProbability": 0.0,
  "misleadingProbabilityRationale": "why this risk score was chosen",
  "visualAuthenticityRisk": 0.0,
  "visualAuthenticityRationale": "why the visual authenticity risk was chosen",
  "depictedEvent": "short description of the event shown, or null",
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

Temporal consistency metadata:
{json.dumps(temporal_packet, ensure_ascii=False)[:8000]}

Additional sampled-frame visual event metadata:
{json.dumps(visual_event_packet, ensure_ascii=False)[:12000]}
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
        "visualAuthenticityRisk": _normalize_probability(
            parsed.get("visualAuthenticityRisk")
        ),
        "visualAuthenticityRationale": str(
            parsed.get("visualAuthenticityRationale") or ""
        ).strip()[:800],
        "depictedEvent": parsed.get("depictedEvent")
        if isinstance(parsed.get("depictedEvent"), str)
        else None,
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


def _estimate_visual_authenticity_risk(
    *,
    keyframe_analysis: dict,
    temporal_analysis: dict | None,
    visual_event_analysis: dict | None,
    parsed: dict,
) -> dict[str, Any]:
    model_risk = _normalize_probability(parsed.get("visualAuthenticityRisk"))
    signals: list[str] = []
    depicted_events: list[str] = []
    synthetic_scores: list[float] = []

    analyzed_frames = list(keyframe_analysis.get("frames", []) or [])
    analyzed_frames.extend((visual_event_analysis or {}).get("frames", []) or [])

    for frame in analyzed_frames:
        indicators = frame.get("vision", {}).get("indicators", {})
        synthetic = indicators.get("synthetic") or {}
        ai_likelihood = synthetic.get("aiLikelihood")
        if ai_likelihood == "high":
            synthetic_scores.append(0.85)
            signals.append("gemini_high_synthetic_likelihood")
        elif ai_likelihood == "medium":
            synthetic_scores.append(0.55)
            signals.append("gemini_medium_synthetic_likelihood")
        elif ai_likelihood == "low":
            synthetic_scores.append(0.15)

        for signal in synthetic.get("signals") or []:
            signals.append(f"visual_{signal}")
            if signal in {
                "impossible_physics",
                "implausible_explosion",
                "impossible_smoke",
                "unnatural_fire",
                "debris_discontinuity",
                "object_disappearance",
                "texture_smearing",
                "cgi_artifacts",
            }:
                synthetic_scores.append(0.72)

        destructive_event = indicators.get("destructiveEvent") or {}
        event_type = destructive_event.get("type")
        event_confidence = destructive_event.get("confidence")
        if event_type and event_type not in {"none", "unknown"}:
            depicted_events.append(event_type)
            signals.append(f"depicts_{event_type}_{event_confidence or 'low'}")

    temporal_summary = (temporal_analysis or {}).get("summary") or {}
    visual_event_summary = (visual_event_analysis or {}).get("summary") or {}
    event_window_consistency = (visual_event_analysis or {}).get(
        "eventWindowConsistency"
    ) or {}
    temporal_ai_risk = _normalize_probability(temporal_summary.get("aiVisualRiskScore"))
    event_authenticity_risk = _normalize_probability(
        visual_event_summary.get("authenticityRiskScore")
    )
    event_consistency_risk = _normalize_probability(
        event_window_consistency.get("overallTemporalAuthenticityRisk")
    )
    object_disappearance_risk = _normalize_probability(
        temporal_summary.get("objectDisappearanceRisk")
    )
    temporal_instability = _normalize_probability(
        temporal_summary.get("temporalInstabilityScore")
    )

    for signal in temporal_summary.get("riskSignals") or []:
        signals.append(f"temporal_{signal}")

    risk_candidates = [score for score in synthetic_scores]
    event_synthetic_likelihood = visual_event_summary.get("highestSyntheticLikelihood")
    if event_synthetic_likelihood == "high":
        risk_candidates.append(0.9)
        signals.append("event_scan_high_synthetic_likelihood")
    elif event_synthetic_likelihood == "medium":
        risk_candidates.append(0.68)
        signals.append("event_scan_medium_synthetic_likelihood")
    for signal in visual_event_summary.get("syntheticSignals") or []:
        signals.append(f"event_scan_{signal}")
    for signal in visual_event_summary.get("authenticityRiskSignals") or visual_event_summary.get("authenticitySignals") or []:
        signals.append(f"authenticity_{signal}")
    for signal in event_window_consistency.get("riskSignals") or []:
        signals.append(f"event_window_{signal}")
    if model_risk is not None:
        risk_candidates.append(model_risk)
    if temporal_ai_risk is not None:
        risk_candidates.append(temporal_ai_risk)
    if event_authenticity_risk is not None:
        risk_candidates.append(event_authenticity_risk)
    if event_consistency_risk is not None:
        risk_candidates.append(event_consistency_risk)
    if object_disappearance_risk is not None:
        risk_candidates.append(object_disappearance_risk * 0.85)
    if temporal_instability is not None and temporal_instability >= 0.55:
        risk_candidates.append(temporal_instability * 0.6)

    visual_risk = max(risk_candidates) if risk_candidates else None
    depicted_event = _most_common(depicted_events)
    if visual_risk is None:
        visual_risk = 0.0

    if depicted_event and visual_risk >= 0.3:
        visual_risk = max(visual_risk, 0.45)
    if depicted_event in {"explosion", "fire", "collapse", "crash", "smoke"}:
        strong_synthetic_signal = any(
            signal
            for signal in signals
            if (
                "synthetic_likelihood" in signal
                or "impossible_physics" in signal
                or "implausible_explosion" in signal
                or "impossible_smoke" in signal
                or "unnatural_fire" in signal
                or "debris_discontinuity" in signal
                or "object_disappearance" in signal
                or "texture_smearing" in signal
                or "cgi_artifacts" in signal
            )
        )
        if strong_synthetic_signal:
            visual_risk = max(visual_risk, 0.72)

    unique_signals = sorted(set(signals))[:16]
    rationale_parts = []
    if model_risk is not None:
        rationale_parts.append(f"model visual risk={round(model_risk * 100)}%")
    if synthetic_scores:
        rationale_parts.append("Gemini reported synthetic visual indicators")
    if temporal_ai_risk is not None:
        rationale_parts.append(f"temporal AI risk={round(temporal_ai_risk * 100)}%")
    if event_authenticity_risk is not None:
        rationale_parts.append(
            f"dedicated authenticity risk={round(event_authenticity_risk * 100)}%"
        )
    if event_consistency_risk is not None:
        rationale_parts.append(
            f"event-window consistency risk={round(event_consistency_risk * 100)}%"
        )
    if event_synthetic_likelihood in {"medium", "high"}:
        rationale_parts.append(
            f"sampled event scan synthetic likelihood={event_synthetic_likelihood}"
        )
    if depicted_event:
        rationale_parts.append(f"depicted event: {depicted_event}")
    if not rationale_parts:
        rationale_parts.append("no strong visual authenticity signals detected")

    return {
        "visualAuthenticityRisk": round(max(0.0, min(1.0, visual_risk)), 4),
        "visualAuthenticityRationale": "; ".join(rationale_parts)[:800],
        "visualAuthenticitySignals": unique_signals,
        "depictedEvent": depicted_event,
    }


def _merge_visual_risk_into_misleading_probability(
    *,
    misleading_probability: float | None,
    visual_authenticity_risk: float | None,
    verdict: Any,
    depicted_event: str | None,
) -> float | None:
    if visual_authenticity_risk is None:
        return misleading_probability

    base = misleading_probability if misleading_probability is not None else 0.0
    if verdict == "no_clear_claim" and depicted_event:
        visual_floor = visual_authenticity_risk * 0.9
    elif depicted_event:
        visual_floor = visual_authenticity_risk * 0.75
    else:
        visual_floor = visual_authenticity_risk * 0.55

    return round(max(base, min(1.0, visual_floor)), 4)


def _normalize_probability(value: Any) -> float | None:
    if isinstance(value, (int, float)) and value == value:
        return max(0.0, min(1.0, float(value)))
    return None


def _most_common(values: list[str]) -> str | None:
    if not values:
        return None
    return max(set(values), key=values.count)


def _apply_visual_authenticity_guardrails(normalized: dict) -> dict:
    visual_risk = normalized.get("visualAuthenticityRisk")
    depicted_event = normalized.get("depictedEvent")
    if not isinstance(visual_risk, (int, float)) or visual_risk < 0.6:
        return normalized

    if depicted_event:
        normalized["recommendedAction"] = "flag_for_review"
        normalized["misleadingProbability"] = max(
            normalized.get("misleadingProbability") or 0.0,
            0.75 if visual_risk >= 0.72 else 0.6,
        )
        if normalized.get("verdict") in {"true", "mostly_true", "no_clear_claim"}:
            normalized["verdict"] = "unverified"
        normalized["summary"] = (
            (normalized.get("summary") or "").strip()
            + " Visual authenticity signals indicate the footage may not be authentic documentation of the depicted event."
        ).strip()[:1200]

    return normalized


def _apply_visual_event_fallback(
    normalized: dict,
    *,
    keyframe_analysis: dict,
    visual_event_analysis: dict | None,
) -> dict:
    visual_description = _best_visual_description(
        keyframe_analysis=keyframe_analysis,
        visual_event_analysis=visual_event_analysis,
    )
    if not visual_description:
        return normalized

    existing_claim = str(normalized.get("claim") or "").strip().lower()
    if existing_claim and "no clear" not in existing_claim:
        return normalized

    normalized["claim"] = (
        "The video visually presents this scene or event as real footage: "
        f"{visual_description}."
    )
    normalized["claimType"] = "event" if normalized.get("depictedEvent") else "other"
    normalized["verdict"] = "unverified"
    normalized["confidence"] = normalized.get("confidence") or 0.4
    normalized["recommendedAction"] = (
        "flag_for_review"
        if normalized.get("visualAuthenticityRisk")
        and normalized["visualAuthenticityRisk"] >= 0.45
        else "needs_more_evidence"
    )
    normalized["misleadingProbability"] = max(
        normalized.get("misleadingProbability") or 0.0,
        0.45,
    )

    visual_rationale = normalized.get("visualAuthenticityRationale") or ""
    normalized["summary"] = (
        "No explicit spoken or written factual claim was detected, but the visuals "
        f"show {visual_description}. Treating the visual presentation itself as an "
        "implied claim about what the footage depicts. "
        + (
            f"Visual authenticity assessment: {visual_rationale}"
            if visual_rationale
            else "The depicted scene is unverified."
        )
    )[:1200]

    if not normalized.get("misleadingProbabilityRationale"):
        normalized["misleadingProbabilityRationale"] = (
            "The video presents a visual scene without enough reliable context to "
            "verify what it depicts or whether the footage is authentic."
        )

    return normalized


def _remove_unsupported_web_specifics(
    normalized: dict,
    *,
    transcript: dict,
    keyframe_analysis: dict,
    visual_event_analysis: dict | None,
) -> dict:
    claim_text = " ".join(
        str(value or "")
        for value in (
            normalized.get("claim"),
            normalized.get("summary"),
            normalized.get("depictedEvent"),
        )
    )
    if not _has_specific_event_details(claim_text):
        return normalized

    source_context = _video_grounding_text(
        transcript=transcript,
        keyframe_analysis=keyframe_analysis,
        visual_event_analysis=visual_event_analysis,
    )
    unsupported_specifics = [
        detail for detail in _specific_event_details(claim_text)
        if detail.lower() not in source_context
    ]
    if not unsupported_specifics:
        return normalized

    visual_description = _best_visual_description(
        keyframe_analysis=keyframe_analysis,
        visual_event_analysis=visual_event_analysis,
    )
    if not visual_description:
        visual_description = normalized.get("depictedEvent") or "the depicted scene"

    normalized["claim"] = (
        "The video visually presents this scene or event as real footage: "
        f"{visual_description}."
    )
    normalized["depictedEvent"] = visual_description
    normalized["verdict"] = "unverified"
    normalized["recommendedAction"] = "flag_for_review"
    normalized["summary"] = (
        "The video metadata does not support the specific location, date, casualty, "
        "cause, or named-incident details introduced by web search. Based on the "
        f"video itself, it depicts: {visual_description}. "
        "Those details should be treated as unverified unless they appear in the "
        "video transcript, visible text, or metadata."
    )[:1200]
    normalized["missingContext"] = sorted(
        set(
            (normalized.get("missingContext") or [])
            + [
                "The video does not provide enough location/date/source context to match it to a specific real-world incident.",
                "Web search found similar event context, but those details are not grounded in the video metadata.",
            ]
        )
    )[:8]
    return normalized


def _video_grounding_text(
    *,
    transcript: dict,
    keyframe_analysis: dict,
    visual_event_analysis: dict | None,
) -> str:
    parts = [(transcript.get("text") or "")]
    for packet in (keyframe_analysis, visual_event_analysis or {}):
        for frame in packet.get("frames", []) or []:
            indicators = frame.get("vision", {}).get("indicators", {}) or {}
            parts.append(str(indicators.get("sceneDescription") or ""))
            parts.extend(str(item) for item in indicators.get("notableObjects") or [])
            parts.extend(str(item) for item in indicators.get("notableActions") or [])
            for item in indicators.get("visibleText") or []:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or ""))
    return " ".join(parts).lower()


def _has_specific_event_details(text: str) -> bool:
    return bool(_specific_event_details(text))


def _specific_event_details(text: str) -> list[str]:
    details: list[str] = []
    details.extend(
        match.group(0)
        for match in re.finditer(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
            r"Dec(?:ember)?)\s+\d{1,2},\s+\d{4}\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    details.extend(
        match.group(0)
        for match in re.finditer(
            r"\b(?:at least\s+)?\d+\s+(?:deaths?|dead|injur(?:y|ies|ed)|fatalit(?:y|ies))\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    details.extend(
        match.group(0)
        for match in re.finditer(
            r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\s+"
            r"(?:apartment|house|building|school|plant|factory|pipeline|center)\b",
            text,
        )
    )
    details.extend(
        match.group(1)
        for match in re.finditer(
            r"\b(?:in|at|near)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b",
            text,
        )
    )
    for phrase in (
        "natural gas pipeline",
        "construction crew",
        "emergency responders",
        "search and recovery",
        "reunification center",
    ):
        if phrase in text.lower():
            details.append(phrase)
    return [detail for detail in details if detail.strip()]


def _visual_metadata_quality(
    *,
    keyframe_analysis: dict,
    visual_event_analysis: dict | None,
) -> dict:
    frame_count = 0
    meaningful_count = 0
    vision_error_count = 0
    sample_errors: list[str] = []

    for packet in (keyframe_analysis, visual_event_analysis or {}):
        for frame in packet.get("frames", []) or []:
            frame_count += 1
            vision = frame.get("vision", {}) or {}
            error = vision.get("error")
            if error:
                vision_error_count += 1
                if len(sample_errors) < 3:
                    sample_errors.append(str(error)[:300])

            indicators = vision.get("indicators", {}) or {}
            if _frame_has_meaningful_visual_metadata(indicators):
                meaningful_count += 1

    return {
        "frameCount": frame_count,
        "meaningfulFrameCount": meaningful_count,
        "visionErrorCount": vision_error_count,
        "sampleVisionErrors": sample_errors,
    }


def _frame_has_meaningful_visual_metadata(indicators: dict) -> bool:
    scene = str(indicators.get("sceneDescription") or "").strip().lower()
    if scene and scene not in {"unknown", "blank", "none"}:
        return True
    if indicators.get("notableObjects") or indicators.get("notableActions"):
        return True
    if indicators.get("visibleText"):
        return True
    destructive_event = indicators.get("destructiveEvent") or {}
    return destructive_event.get("type") not in {None, "none", "unknown"}


def _best_visual_description(
    *,
    keyframe_analysis: dict,
    visual_event_analysis: dict | None,
) -> str | None:
    candidates: list[str] = []
    for packet in (visual_event_analysis or {}, keyframe_analysis):
        for frame in packet.get("frames", []) or []:
            indicators = frame.get("vision", {}).get("indicators", {})
            scene_description = indicators.get("sceneDescription")
            if isinstance(scene_description, str) and scene_description.strip():
                candidates.append(scene_description.strip())

            actions = _string_list(indicators.get("notableActions"), limit=4)
            objects = _string_list(indicators.get("notableObjects"), limit=4)
            if actions or objects:
                parts = []
                if actions:
                    parts.append("actions: " + ", ".join(actions))
                if objects:
                    parts.append("objects: " + ", ".join(objects))
                candidates.append("; ".join(parts))

            destructive_event = indicators.get("destructiveEvent") or {}
            event_type = destructive_event.get("type")
            if event_type not in {None, "none", "unknown"}:
                candidates.append(f"a {event_type} event")

            visible_text = indicators.get("visibleText") or []
            text_items = [
                str(item.get("text") or "").strip()
                for item in visible_text
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ][:4]
            if text_items:
                candidates.append("visible text: " + "; ".join(text_items))

    for candidate in candidates:
        cleaned = " ".join(candidate.split())
        if len(cleaned) >= 12:
            return cleaned[:220]

    if not candidates:
        return None
    return candidates[0][:220]


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
        "visualAuthenticityRisk": None,
        "visualAuthenticityRationale": "",
        "visualAuthenticitySignals": [],
        "depictedEvent": None,
        "summary": "",
        "evidence": [],
        "sources": [],
        "missingContext": [],
        "videoSignalsUsed": [],
        "recommendedAction": "needs_more_evidence",
    }
