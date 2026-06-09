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


def upload_to_supabase_storage(
    *,
    bucket: str,
    storage_path: str,
    local_path: Path,
    content_type: str,
) -> str:
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
