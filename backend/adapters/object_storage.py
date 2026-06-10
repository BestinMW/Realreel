import os
from pathlib import Path

import httpx


class SupabaseStorageUploadError(RuntimeError):
    def __init__(self, *, storage_path: str, status_code: int, message: str) -> None:
        """Initialize a Supabase Storage upload failure.

        Args:
            storage_path (str): Object path that failed to upload.
            status_code (int): HTTP status code from the storage API.
            message (str): Error body or message from the storage API.

        Returns:
            None
        """
        self.storage_path = storage_path
        self.status_code = status_code
        self.message = message
        super().__init__(
            f"Failed to upload {storage_path} to Supabase Storage: {message}"
        )

    @property
    def is_payload_too_large(self) -> bool:
        """Whether the upload failed because the payload exceeded storage size limits.

        Args:
            None

        Returns:
            bool: ``True`` when the HTTP status is 413 or the error message indicates
            payload-too-large; otherwise ``False``.
        """
        lowered = self.message.lower()
        return (
            self.status_code == 413
            or '"statuscode":"413"' in lowered.replace(" ", "")
            or "payload too large" in lowered
            or "maximum allowed size" in lowered
        )


def get_supabase_config() -> tuple[str, str]:
    """Read Supabase URL and service-role key from environment variables.

    Args:
        None

    Returns:
        tuple[str, str]: ``(supabase_url, service_role_key)`` with trailing slash stripped
        from the URL. Raises ``RuntimeError`` when either value is missing.
    """
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_role_key:
        raise RuntimeError(
            "Supabase storage is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )
    return supabase_url, service_role_key


_ensured_bucket_names: set[str] = set()


def ensure_storage_buckets(bucket_names: set[str]) -> None:
    """Create required private Supabase buckets if they do not exist.

    Args:
        bucket_names (set[str]): Bucket names that must exist before uploads.

    Returns:
        None. Raises ``RuntimeError`` when listing or creating buckets fails.
    """
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
    """Upload one pipeline artifact to Supabase Storage.

    Args:
        bucket (str): Supabase Storage bucket name.
        storage_path (str): Object path inside the bucket.
        local_path (Path): Local file to upload.
        content_type (str): MIME type sent as ``Content-Type``.

    Returns:
        str: The ``storage_path`` on success. Raises ``SupabaseStorageUploadError`` when
        the upload HTTP response is 4xx/5xx (including payload-too-large / 413).
        Raises ``RuntimeError`` when Supabase credentials are not configured.
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
    """URL-encode a path segment for Supabase Storage object keys.

    Args:
        value (str): Raw segment to encode.

    Returns:
        str: Percent-encoded string safe for use in storage URLs.
    """
    from urllib.parse import quote as url_quote

    return url_quote(value, safe="")
