from urllib.parse import parse_qs, urlparse


def parse_video_url(value: str | None) -> dict[str, str] | None:
    if not value or not isinstance(value, str):
        return None

    original_url = value.strip()

    try:
        url = urlparse(original_url)
    except ValueError:
        return None

    if url.scheme not in {"http", "https"}:
        return None

    host = url.hostname.replace("www.", "") if url.hostname else ""

    youtube_id = _parse_youtube_id(host, url.path, url.query)
    if youtube_id:
        return {"platform": "youtube", "id": youtube_id, "url": original_url}

    tiktok_id = _parse_tiktok_id(host, url.path)
    if tiktok_id:
        return {"platform": "tiktok", "id": tiktok_id, "url": original_url}

    instagram_id = _parse_instagram_id(host, url.path)
    if instagram_id:
        return {"platform": "instagram", "id": instagram_id, "url": original_url}

    direct_id = _parse_direct_video_id(host, url.path)
    if direct_id:
        return {"platform": "direct", "id": direct_id, "url": original_url}

    return None


def parse_youtube_url(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None

    try:
        url = urlparse(value.strip())
    except ValueError:
        return None

    host = url.hostname.replace("www.", "") if url.hostname else ""
    return _parse_youtube_id(host, url.path, url.query)


def _parse_youtube_id(host: str, path: str, query: str) -> str | None:
    is_youtube_host = host in {
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }

    if not is_youtube_host:
        return None

    if host == "youtu.be":
        parts = [part for part in path.split("/") if part]
        return parts[0] if parts else None

    if path == "/watch":
        return parse_qs(query).get("v", [None])[0]

    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"}:
        return parts[1]

    return None


def _parse_tiktok_id(host: str, path: str) -> str | None:
    if not (host == "tiktok.com" or host.endswith(".tiktok.com")):
        return None

    parts = [part for part in path.split("/") if part]
    if not parts:
        return None

    if len(parts) >= 3 and parts[0].startswith("@") and parts[1] == "video":
        return parts[2]

    if host in {"vm.tiktok.com", "vt.tiktok.com"}:
        return parts[0]

    if len(parts) >= 2 and parts[0] in {"t", "embed"}:
        return parts[-1]

    return safe_segment("-".join(parts)) or None


def _parse_instagram_id(host: str, path: str) -> str | None:
    if not (host == "instagram.com" or host.endswith(".instagram.com")):
        return None

    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"reel", "reels", "p", "tv"}:
        return parts[1]

    if len(parts) >= 3 and parts[0] == "stories":
        return parts[2]

    return None


def _parse_direct_video_id(host: str, path: str) -> str | None:
    if not host:
        return None

    suffixes = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
    normalized_path = path.lower()
    if not any(normalized_path.endswith(suffix) for suffix in suffixes):
        return None

    parts = [part for part in path.split("/") if part]
    if parts:
        return safe_segment(parts[-1])

    return safe_segment(host)


def safe_segment(value: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)
