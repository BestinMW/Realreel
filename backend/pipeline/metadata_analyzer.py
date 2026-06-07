from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .metadataCollector import (
    get_embedded_metadata,
    get_platform_metadata,
    get_video_metadata,
)

RECENCY_PHRASES = (
    r"\btoday\b",
    r"\bjust happened\b",
    r"\bbreaking\b",
    r"\blive\b",
    r"\bcurrently\b",
    r"\bright now\b",
)

CLAIMED_SOURCE_PHRASES = (
    r"\bsecurity camera\b",
    r"\bcctv\b",
    r"\bsurveillance footage\b",
    r"\braw footage\b",
)

EDITING_ENCODER_MARKERS = (
    "capcut",
    "adobe",
    "premiere",
    "davinci",
    "ffmpeg",
)

CREATION_DATE_KEYS = (
    "creationdate",
    "createdate",
    "mediacreatedate",
    "trackcreatedate",
    "datetimeoriginal",
    "creation_time",
    "datecreated",
)

ENCODER_KEYS = (
    "encoder",
    "compressorname",
    "compressor",
    "encodedby",
)

SOFTWARE_KEYS = (
    "software",
    "creatortool",
    "toolname",
    "application",
)

DEVICE_MODEL_KEYS = (
    "devicemodel",
    "devicemodelname",
    "model",
    "cameramodel",
    "cameramodelname",
    "make",
)


@dataclass(frozen=True)
class RuleResult:
    flagged: bool
    score: float
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CollectedMetadata:
    platform: dict[str, Any]
    video: dict[str, Any]
    embedded: list[dict[str, Any]]
    embedded_tags: dict[str, Any]
    collection_errors: list[str]


class MetadataAnalyzer:
    """Rule-based analysis over platform, file, and embedded video metadata."""

    def __init__(self, url: str, video_path: Path | str) -> None:
        self.url = url.strip()
        self.video_path = Path(video_path)

    def analyze(
        self,
        transcript_text: str | None = None,
        repost_match_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Collect metadata and evaluate misinformation / repost heuristics.

        Returns a JSON-serializable dict with metadata_score, reasons, and rule_results.
        """
        collected = self._collect_metadata()
        transcript = (transcript_text or "").strip().lower()

        rule_results = {
            "creation_date_conflict": self._rule_creation_date_conflict(
                transcript, collected
            ),
            "reencoded_edited": self._rule_reencoded_edited(collected),
            "missing_metadata": self._rule_missing_metadata(collected),
            "repost_age_mismatch": self._rule_repost_age_mismatch(
                collected, repost_match_date
            ),
            "metadata_vs_claimed_source": self._rule_metadata_vs_claimed_source(
                transcript, collected
            ),
        }

        serialized_rules = {
            name: result.to_dict() for name, result in rule_results.items()
        }
        triggered_scores = [
            result.score for result in rule_results.values() if result.flagged
        ]
        reasons = [
            result.reason
            for result in rule_results.values()
            if result.flagged and result.reason
        ]

        return {
            "metadata_score": round(min(sum(triggered_scores), 1.0), 4),
            "reasons": reasons,
            "rule_results": serialized_rules,
            "collection_errors": collected.collection_errors,
        }

    def _collect_metadata(self) -> CollectedMetadata:
        errors: list[str] = []
        platform: dict[str, Any] = {}
        video: dict[str, Any] = {}
        embedded: list[dict[str, Any]] = []

        try:
            platform = get_platform_metadata(self.url)
        except Exception as exc:
            errors.append(f"platform: {exc}")

        try:
            video = get_video_metadata(self.video_path)
        except Exception as exc:
            errors.append(f"video: {exc}")

        try:
            embedded = get_embedded_metadata(self.video_path)
        except Exception as exc:
            errors.append(f"embedded: {exc}")

        embedded_tags = embedded[0] if embedded else {}
        if not isinstance(embedded_tags, dict):
            embedded_tags = {}

        return CollectedMetadata(
            platform=platform,
            video=video,
            embedded=embedded,
            embedded_tags=embedded_tags,
            collection_errors=errors,
        )

    def _rule_creation_date_conflict(
        self, transcript: str, collected: CollectedMetadata
    ) -> RuleResult:
        if not self._transcript_matches_any(transcript, RECENCY_PHRASES):
            return RuleResult(flagged=False, score=0.0)

        creation_date = self._extract_creation_date(collected)
        if creation_date is None:
            return RuleResult(flagged=False, score=0.0)

        cutoff = date.today() - timedelta(days=30)
        if creation_date.date() < cutoff:
            return RuleResult(
                flagged=True,
                score=0.9,
                reason="Video creation date predates claimed event.",
            )
        return RuleResult(flagged=False, score=0.0)

    def _rule_reencoded_edited(self, collected: CollectedMetadata) -> RuleResult:
        encoder_value = self._extract_encoder(collected)
        if encoder_value and self._contains_editing_marker(encoder_value):
            return RuleResult(
                flagged=True,
                score=0.2,
                reason="Video appears edited or re-encoded.",
            )
        return RuleResult(flagged=False, score=0.0)

    def _rule_missing_metadata(self, collected: CollectedMetadata) -> RuleResult:
        missing_count = sum(
            1
            for value in (
                self._extract_creation_time_field(collected),
                self._extract_encoder(collected),
                self._extract_software(collected),
                self._extract_device_model(collected),
            )
            if not value
        )
        if missing_count >= 3:
            return RuleResult(
                flagged=True,
                score=0.1,
                reason="Limited original metadata available.",
            )
        return RuleResult(flagged=False, score=0.0)

    def _rule_repost_age_mismatch(
        self,
        collected: CollectedMetadata,
        repost_match_date: str | None,
    ) -> RuleResult:
        if not repost_match_date:
            return RuleResult(flagged=False, score=0.0)

        match_date = self.parse_date(repost_match_date)
        upload_date = self._extract_platform_upload_date(collected.platform)
        if match_date is None or upload_date is None:
            return RuleResult(flagged=False, score=0.0)

        if (upload_date - match_date.date()).days > 180:
            return RuleResult(
                flagged=True,
                score=0.8,
                reason="Similar footage found from an earlier upload.",
            )
        return RuleResult(flagged=False, score=0.0)

    def _rule_metadata_vs_claimed_source(
        self, transcript: str, collected: CollectedMetadata
    ) -> RuleResult:
        if not self._transcript_matches_any(transcript, CLAIMED_SOURCE_PHRASES):
            return RuleResult(flagged=False, score=0.0)

        fps = self._extract_video_fps(collected.video)
        encoder_value = self._extract_encoder(collected)
        high_fps = fps is not None and fps > 30
        edited_encoder = bool(
            encoder_value and self._contains_editing_marker(encoder_value)
        )

        if high_fps or edited_encoder:
            return RuleResult(
                flagged=True,
                score=0.5,
                reason="Metadata is inconsistent with the claimed source.",
            )
        return RuleResult(flagged=False, score=0.0)

    @staticmethod
    def parse_date(value: str | int | float | None) -> datetime | None:
        """Parse common metadata date formats into a timezone-aware datetime."""
        if value is None:
            return None

        if isinstance(value, (int, float)):
            timestamp = float(value)
            if timestamp > 1_000_000_000_000:
                timestamp /= 1000.0
            try:
                return datetime.fromtimestamp(timestamp, tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                return None

        text = str(value).strip()
        if not text:
            return None

        if re.fullmatch(r"\d{8}", text):
            try:
                parsed = datetime.strptime(text, "%Y%m%d").replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                pass

        normalized = text.replace("Z", "+00:00").replace("/", "-")
        normalized = re.sub(r"(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", normalized)
        normalized = normalized.replace(" ", "T", 1) if " " in normalized and "T" not in normalized else normalized

        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass

        for fmt in (
            "%m/%d/%y",
            "%m/%d/%Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y:%m:%d %H:%M:%S",
            "%Y:%m:%d",
        ):
            try:
                parsed = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                continue

        return None

    def _extract_platform_upload_date(self, platform: dict[str, Any]) -> date | None:
        for key in ("upload_date", "release_date", "timestamp"):
            parsed = self.parse_date(platform.get(key))
            if parsed is not None:
                return parsed.date()
        return None

    def _extract_creation_date(self, collected: CollectedMetadata) -> datetime | None:
        for key, value in collected.embedded_tags.items():
            normalized_key = self._normalize_key(key)
            if any(marker in normalized_key for marker in CREATION_DATE_KEYS):
                parsed = self.parse_date(value if not isinstance(value, dict) else None)
                if parsed is not None:
                    return parsed

        format_tags = (collected.video.get("format") or {}).get("tags") or {}
        if isinstance(format_tags, dict):
            for key in ("creation_time", "date", "creationdate"):
                parsed = self.parse_date(format_tags.get(key))
                if parsed is not None:
                    return parsed
        return None

    def _extract_creation_time_field(self, collected: CollectedMetadata) -> str | None:
        value = self._extract_creation_date(collected)
        if value is not None:
            return value.isoformat()
        return self._find_tag_value(collected, CREATION_DATE_KEYS)

    def _extract_encoder(self, collected: CollectedMetadata) -> str | None:
        encoder = self._find_tag_value(collected, ENCODER_KEYS)
        if encoder:
            return encoder

        format_tags = (collected.video.get("format") or {}).get("tags") or {}
        if isinstance(format_tags, dict):
            for key in ("encoder", "encoded_by", "encoding_tool"):
                value = format_tags.get(key)
                if value:
                    return str(value)
        return None

    def _extract_software(self, collected: CollectedMetadata) -> str | None:
        return self._find_tag_value(collected, SOFTWARE_KEYS)

    def _extract_device_model(self, collected: CollectedMetadata) -> str | None:
        device = self._find_tag_value(collected, DEVICE_MODEL_KEYS)
        if device:
            return device

        make = self._find_tag_value(collected, ("make",))
        model = self._find_tag_value(collected, ("model", "cameramodelname"))
        if make and model:
            return f"{make} {model}"
        return make or model

    def _extract_video_fps(self, video: dict[str, Any]) -> float | None:
        streams = video.get("streams") or []
        video_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "video"),
            None,
        )
        if not video_stream:
            return None

        for rate_key in ("avg_frame_rate", "r_frame_rate"):
            fps = self._parse_fraction(video_stream.get(rate_key))
            if fps is not None and fps > 0:
                return fps
        return None

    @staticmethod
    def _parse_fraction(value: Any) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text == "0/0":
            return None
        if "/" in text:
            num, den = text.split("/", 1)
            try:
                denominator = float(den)
                if denominator == 0:
                    return None
                return float(num) / denominator
            except ValueError:
                return None
        try:
            return float(text)
        except ValueError:
            return None

    def _find_tag_value(
        self, collected: CollectedMetadata, key_markers: tuple[str, ...]
    ) -> str | None:
        for key, value in collected.embedded_tags.items():
            normalized_key = self._normalize_key(key)
            if any(marker in normalized_key for marker in key_markers):
                if value is None:
                    continue
                if isinstance(value, (str, int, float)):
                    text = str(value).strip()
                    if text:
                        return text
        return None

    @staticmethod
    def _normalize_key(key: str) -> str:
        return re.sub(r"[^a-z0-9]", "", key.lower())

    @staticmethod
    def _contains_editing_marker(encoder_value: str) -> bool:
        lowered = encoder_value.lower()
        return any(marker in lowered for marker in EDITING_ENCODER_MARKERS)

    @staticmethod
    def _transcript_matches_any(transcript: str, patterns: tuple[str, ...]) -> bool:
        if not transcript:
            return False
        return any(re.search(pattern, transcript, re.IGNORECASE) for pattern in patterns)


if __name__ == "__main__":
    example = MetadataAnalyzer(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        video_path=Path("example/source.mp4"),
    )
    print(
        json.dumps(
            {
                "note": "Run against a real downloaded file to evaluate rules.",
                "example_analyze_call": {
                    "transcript_text": "Breaking news today from CCTV security camera footage.",
                    "repost_match_date": "20220101",
                },
                "sample_not_flagged": RuleResult(flagged=False, score=0.0).to_dict(),
                "sample_flagged": RuleResult(
                    flagged=True,
                    score=0.9,
                    reason="Video creation date predates claimed event.",
                ).to_dict(),
            },
            indent=2,
        )
    )
    print(
        "\nLive run (requires example/source.mp4 and tools):\n"
        f"  analyzer = MetadataAnalyzer(url=..., video_path=...)\n"
        f"  result = analyzer.analyze(transcript_text=..., repost_match_date=...)\n"
    )
