from urllib.parse import parse_qs, urlparse


def parse_youtube_url(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None

    try:
        url = urlparse(value.strip())
    except ValueError:
        return None

    host = url.hostname.replace("www.", "") if url.hostname else ""
    is_youtube_host = host in {
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }

    if not is_youtube_host:
        return None

    if host == "youtu.be":
        parts = [part for part in url.path.split("/") if part]
        return parts[0] if parts else None

    if url.path == "/watch":
        return parse_qs(url.query).get("v", [None])[0]

    parts = [part for part in url.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"}:
        return parts[1]

    return None


def safe_segment(value: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)
