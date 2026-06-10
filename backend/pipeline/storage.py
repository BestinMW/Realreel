import os
from pathlib import Path

import httpx


class SupabaseStorageUploadError(RuntimeError):
    def __init__(self, *, storage_path: str, status_code: int, message: str) -> None:
        self.storage_path = storage_path
        self.status_code = status_code
        self.message = message
        super().__init__(
            f"Failed to upload {storage_path} to Supabase Storage: {message}"
        )

    @property
    def is_payload_too_large(self) -> bool:
        lowered = self.message.lower()
        return (
            self.status_code == 413
            or '"statuscode":"413"' in lowered.replace(" ", "")
            or "payload too large" in lowered
            or "maximum allowed size" in lowered
        )


def get_supabase_config() -> tuple[str, str]:
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_role_key:
        raise RuntimeError(
            "Supabase storage is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )
    return supabase_url, service_role_key


_ensured_bucket_names: set[str] = set()


def ensure_storage_buckets(bucket_names: set[str]) -> None:
    """Create required private Supabase buckets if they do not exist."""
    missing = bucket_names - _ensured_bucket_names
    if not missing:
        return

    supabase_url, service_role_key = get_supabase_config()
    headers = {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }
    list_response = httpx.get(
        f"{supabase_url}/storage/v1/bucket",
        headers=headers,
        timeout=30.0,
    )
    if list_response.status_code >= 400:
        raise RuntimeError(
            f"Failed to list Supabase Storage buckets: {list_response.text}"
        )

    existing = {bucket["name"] for bucket in list_response.json()}
    for bucket_name in sorted(missing):
        if bucket_name in existing:
            _ensured_bucket_names.add(bucket_name)
            continue

        create_response = httpx.post(
            f"{supabase_url}/storage/v1/bucket",
            headers=headers,
            json={"name": bucket_name, "public": False},
            timeout=30.0,
        )
        if create_response.status_code >= 400:
            raise RuntimeError(
                f"Failed to create Supabase Storage bucket '{bucket_name}': "
                f"{create_response.text}"
            )
        _ensured_bucket_names.add(bucket_name)


def upload_to_supabase_storage(
    *,
    bucket: str,
    storage_path: str,
    local_path: Path,
    content_type: str,
) -> str:
    """Upload one pipeline artifact to Supabase Storage (engine -> storage contract).

    Args:
        bucket (str): Supabase bucket name (e.g. ``raw-videos``, ``transcripts``,
            ``thumbnails``, ``analysis``).
        storage_path (str): Object path within the bucket.
        local_path (Path): Local file to upload.
        content_type (str): MIME type for the uploaded object.

    Returns:
        str: The ``storage_path`` on success (reported in the ``complete`` result as
        ``rawVideoPath``, ``transcriptPath``, ``claimAnalysisPath``, etc.). Raises
        ``SupabaseStorageUploadError`` when Supabase credentials are missing or the
        upload fails; the engine may skip uploads or include missing paths in the result.
    """
    supabase_url, service_role_key = get_supabase_config()
    from urllib.parse import quote as url_quote

    encoded_path = "/".join(url_quote(segment, safe="") for segment in storage_path.split("/"))
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{encoded_path}"
    file_bytes = local_path.read_bytes()

    response = httpx.post(
        upload_url,
        headers={
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": content_type,
            "Content-Length": str(len(file_bytes)),
            "x-upsert": "true",
        },
        content=file_bytes,
        timeout=300.0,
    )
    if response.status_code >= 400:
        raise SupabaseStorageUploadError(
            storage_path=storage_path,
            status_code=response.status_code,
            message=response.text,
        )
    return storage_path


def quote(value: str) -> str:
    from urllib.parse import quote as url_quote

    return url_quote(value, safe="")
