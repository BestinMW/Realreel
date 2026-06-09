from typing import Any

__all__ = [
    "delete_video_and_assets",
    "find_video_by_sha256",
    "find_video_by_url",
    "get_video_or_raise",
    "list_recent_videos",
    "save_analyzed_video",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from storage.services import videos

        return getattr(videos, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
