from urllib.parse import parse_qs, urlparse


def parse_video_url(value: str | None) -> dict[str, str] | None:
    """Parse a supported video URL into platform metadata.

    Args:
        value (str | None): Raw URL string from user input.

    Returns:
        dict[str, str] | None: Mapping with ``platform``, ``id``, and ``url`` keys
            for YouTube, TikTok, Instagram, or direct video URLs; ``None`` if the
            value is missing, invalid, or unsupported.
    """
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
    """Extract the YouTube video ID from a URL.

    Args:
        value (str | None): YouTube URL in common formats (watch, youtu.be, shorts, etc.).

    Returns:
        str | None: YouTube video ID, or ``None`` if the value is missing, invalid,
            or not a recognized YouTube URL.
    """
    if not value or not isinstance(value, str):
        return None

    try:
        url = urlparse(value.strip())
    except ValueError:
        return None

    host = url.hostname.replace("www.", "") if url.hostname else ""
    return _parse_youtube_id(host, url.path, url.query)


def _parse_youtube_id(host: str, path: str, query: str) -> str | None:
    """Resolve a YouTube video ID from URL components.

    Args:
        host (str): Normalized hostname without a ``www.`` prefix.
        path (str): URL path component.
        query (str): URL query string.

    Returns:
        str | None: YouTube video ID, or ``None`` if the host or path is not YouTube.
    """
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
    """Resolve a TikTok video ID from URL components.

    Args:
        host (str): Normalized hostname without a ``www.`` prefix.
        path (str): URL path component.

    Returns:
        str | None: TikTok video or share ID, or ``None`` if the host or path is
            not a recognized TikTok URL pattern.
    """
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
    """Resolve an Instagram media ID from URL components.

    Args:
        host (str): Normalized hostname without a ``www.`` prefix.
        path (str): URL path component.

    Returns:
        str | None: Instagram reel, post, TV, or story media ID, or ``None`` if
            the host or path is not a recognized Instagram URL pattern.
    """
    if not (host == "instagram.com" or host.endswith(".instagram.com")):
        return None

    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"reel", "reels", "p", "tv"}:
        return parts[1]

    if len(parts) >= 3 and parts[0] == "stories":
        return parts[2]

    return None


def _parse_direct_video_id(host: str, path: str) -> str | None:
    """Resolve a stable ID for a direct video file URL.

    Args:
        host (str): Normalized hostname without a ``www.`` prefix.
        path (str): URL path component.

    Returns:
        str | None: Sanitized filename or host segment used as the video ID, or
            ``None`` if the URL does not point to a supported video file extension.
    """
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
    """Sanitize a string for use as a filesystem-safe identifier segment.

    Args:
        value (str): Raw segment text, such as a filename or URL path part.

    Returns:
        str: Input with non-alphanumeric characters replaced by underscores.
    """
    import re

    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)
