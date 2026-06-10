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
        """Serialize this rule outcome to a plain dict.

        Args:
            None.

        Returns:
            dict[str, Any]: ``flagged``, ``score``, and optional ``reason`` keys.
        """
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
        """Bind a source URL and local video file for metadata analysis.

        Args:
            url: Platform URL used to fetch platform-side metadata.
            video_path: Local path to the downloaded video file.

        Returns:
            None.
        """
        self.url = url.strip()
        self.video_path = Path(video_path)

    def analyze(
        self,
        transcript_text: str | None = None,
        repost_match_date: str | None = None,
    ) -> dict[str, Any]:
        """Collect metadata and evaluate misinformation / repost heuristics.

        Args:
            transcript_text: Optional transcript used for recency and claimed-source rules.
            repost_match_date: Optional earlier-match date string for repost-age comparison.

        Returns:
            dict[str, Any]: JSON-serializable payload with ``metadata_score``, ``reasons``,
                ``rule_results``, and ``collection_errors``.
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
        """Fetch platform, file, and embedded metadata for the bound video.

        Args:
            None.

        Returns:
            CollectedMetadata: Aggregated metadata plus any per-source collection errors.
        """
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
        """Flag when recency language conflicts with an old embedded creation date.

        Args:
            transcript: Lowercased transcript text to scan for recency phrases.
            collected: Metadata bundle from ``_collect_metadata``.

        Returns:
            RuleResult: Flagged when creation date is more than 30 days before today.
        """
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
        """Flag when encoder metadata indicates editing or re-encoding software.

        Args:
            collected: Metadata bundle from ``_collect_metadata``.

        Returns:
            RuleResult: Flagged when the encoder matches known editing markers.
        """
        encoder_value = self._extract_encoder(collected)
        if encoder_value and self._contains_editing_marker(encoder_value):
            return RuleResult(
                flagged=True,
                score=0.2,
                reason="Video appears edited or re-encoded.",
            )
        return RuleResult(flagged=False, score=0.0)

    def _rule_missing_metadata(self, collected: CollectedMetadata) -> RuleResult:
        """Flag when most core provenance fields are absent from metadata.

        Args:
            collected: Metadata bundle from ``_collect_metadata``.

        Returns:
            RuleResult: Flagged when at least three of four key fields are missing.
        """
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
        """Flag when platform upload date is much later than a matched earlier repost.

        Args:
            collected: Metadata bundle from ``_collect_metadata``.
            repost_match_date: Date string for the earlier similar upload, if known.

        Returns:
            RuleResult: Flagged when upload is more than 180 days after the match date.
        """
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
        """Flag when claimed raw-source language conflicts with technical metadata.

        Args:
            transcript: Lowercased transcript text to scan for claimed-source phrases.
            collected: Metadata bundle from ``_collect_metadata``.

        Returns:
            RuleResult: Flagged when FPS or encoder suggests non-raw capture.
        """
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
        """Parse common metadata date formats into a timezone-aware datetime.

        Args:
            value: Timestamp, date string, or ``None`` from metadata fields.

        Returns:
            datetime | None: Parsed UTC-aware datetime, or ``None`` when unparseable.
        """
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
        """Resolve the platform upload or release date from platform metadata.

        Args:
            platform: Platform metadata dict from ``get_platform_metadata``.

        Returns:
            date | None: Upload date when a known field parses successfully.
        """
        for key in ("upload_date", "release_date", "timestamp"):
            parsed = self.parse_date(platform.get(key))
            if parsed is not None:
                return parsed.date()
        return None

    def _extract_creation_date(self, collected: CollectedMetadata) -> datetime | None:
        """Extract the earliest embedded or container creation timestamp.

        Args:
            collected: Metadata bundle from ``_collect_metadata``.

        Returns:
            datetime | None: Parsed creation datetime, or ``None`` when not found.
        """
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
        """Return a string creation-time value for missing-metadata checks.

        Args:
            collected: Metadata bundle from ``_collect_metadata``.

        Returns:
            str | None: ISO creation time or raw tag value, or ``None`` when absent.
        """
        value = self._extract_creation_date(collected)
        if value is not None:
            return value.isoformat()
        return self._find_tag_value(collected, CREATION_DATE_KEYS)

    def _extract_encoder(self, collected: CollectedMetadata) -> str | None:
        """Resolve encoder or compressor metadata from embedded and format tags.

        Args:
            collected: Metadata bundle from ``_collect_metadata``.

        Returns:
            str | None: Encoder name string, or ``None`` when not present.
        """
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
        """Resolve editing or capture software from embedded metadata tags.

        Args:
            collected: Metadata bundle from ``_collect_metadata``.

        Returns:
            str | None: Software or creator-tool string, or ``None`` when absent.
        """
        return self._find_tag_value(collected, SOFTWARE_KEYS)

    def _extract_device_model(self, collected: CollectedMetadata) -> str | None:
        """Resolve camera or device model from embedded metadata tags.

        Args:
            collected: Metadata bundle from ``_collect_metadata``.

        Returns:
            str | None: Device model string, combined make/model, or ``None``.
        """
        device = self._find_tag_value(collected, DEVICE_MODEL_KEYS)
        if device:
            return device

        make = self._find_tag_value(collected, ("make",))
        model = self._find_tag_value(collected, ("model", "cameramodelname"))
        if make and model:
            return f"{make} {model}"
        return make or model

    def _extract_video_fps(self, video: dict[str, Any]) -> float | None:
        """Read the frame rate from the primary video stream in probe output.

        Args:
            video: FFprobe-style video metadata dict from ``get_video_metadata``.

        Returns:
            float | None: Positive FPS value, or ``None`` when unavailable.
        """
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
        """Parse a numeric string or fractional rate such as ``30000/1001``.

        Args:
            value: Frame-rate field value from stream metadata.

        Returns:
            float | None: Parsed numeric rate, or ``None`` when invalid.
        """
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
        """Find the first embedded tag whose normalized key contains a marker.

        Args:
            collected: Metadata bundle from ``_collect_metadata``.
            key_markers: Normalized substrings to match against tag keys.

        Returns:
            str | None: First non-empty scalar tag value, or ``None``.
        """
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
        """Normalize a metadata tag key for case- and punctuation-insensitive lookup.

        Args:
            key: Raw metadata tag key.

        Returns:
            str: Lowercased alphanumeric-only key.
        """
        return re.sub(r"[^a-z0-9]", "", key.lower())

    @staticmethod
    def _contains_editing_marker(encoder_value: str) -> bool:
        """Check whether an encoder string names known editing or transcode tools.

        Args:
            encoder_value: Encoder or compressor metadata string.

        Returns:
            bool: ``True`` when a known editing marker appears in the value.
        """
        lowered = encoder_value.lower()
        return any(marker in lowered for marker in EDITING_ENCODER_MARKERS)

    @staticmethod
    def _transcript_matches_any(transcript: str, patterns: tuple[str, ...]) -> bool:
        """Test whether any regex pattern matches the transcript text.

        Args:
            transcript: Lowercased transcript text to search.
            patterns: Case-insensitive regex patterns to test.

        Returns:
            bool: ``True`` when at least one pattern matches.
        """
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
