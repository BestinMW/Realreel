import os
from pathlib import Path

import httpx


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
        raise RuntimeError(
            f"Failed to upload {storage_path} to Supabase Storage: {response.text}"
        )
    return storage_path


def quote(value: str) -> str:
    from urllib.parse import quote as url_quote

    return url_quote(value, safe="")
