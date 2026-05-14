from __future__ import annotations

import asyncio
import mimetypes
from pathlib import Path

from supabase import Client, create_client

from storage.assets.paths import BUCKET_NAMES, StorageBucket
from storage.core.config import settings


class SupabaseStorageService:
    """Thin service around Supabase Storage.

    Supabase's Python client is synchronous, so public async methods call it in a
    thread. That keeps FastAPI workers responsive while large object operations
    are running.
    """

    def __init__(self, client: Client | None = None) -> None:
        self.client = client or create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )

    async def ensure_buckets(self) -> None:
        """Create required private buckets if they do not exist."""
        await asyncio.to_thread(self._ensure_buckets_sync)

    async def upload_file(
        self,
        *,
        bucket: StorageBucket,
        storage_path: str,
        local_path: str | Path,
        upsert: bool = False,
        content_type: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._upload_file_sync,
            bucket,
            storage_path,
            Path(local_path),
            upsert,
            content_type,
        )

    async def create_signed_url(
        self,
        *,
        bucket: StorageBucket,
        storage_path: str,
        expires_in: int | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self._create_signed_url_sync,
            bucket,
            storage_path,
            expires_in or settings.signed_url_ttl_seconds,
        )

    async def delete_paths(self, *, bucket: StorageBucket, paths: list[str]) -> None:
        if not paths:
            return
        await asyncio.to_thread(self._delete_paths_sync, bucket, paths)

    async def delete_prefix(self, *, bucket: StorageBucket, prefix: str) -> None:
        paths = await asyncio.to_thread(self._list_paths_sync, bucket, prefix)
        await self.delete_paths(bucket=bucket, paths=paths)

    async def delete_prefixes(
        self,
        prefixes_by_bucket: dict[StorageBucket, list[str]],
    ) -> None:
        for bucket, prefixes in prefixes_by_bucket.items():
            for prefix in prefixes:
                await self.delete_prefix(bucket=bucket, prefix=prefix)

    def _ensure_buckets_sync(self) -> None:
        existing = {bucket.name for bucket in self.client.storage.list_buckets()}

        for bucket_name in BUCKET_NAMES.values():
            if bucket_name in existing:
                continue

            # Buckets stay private. Backend returns short-lived signed URLs.
            self.client.storage.create_bucket(
                bucket_name,
                options={"public": False, "file_size_limit": "2GB"},
            )

    def _upload_file_sync(
        self,
        bucket: StorageBucket,
        storage_path: str,
        local_path: Path,
        upsert: bool,
        content_type: str | None,
    ) -> str:
        if not local_path.is_file():
            raise FileNotFoundError(f"File not found: {local_path}")

        resolved_bucket = BUCKET_NAMES[bucket]
        mime_type = content_type or mimetypes.guess_type(local_path.name)[0]

        with local_path.open("rb") as file:
            self.client.storage.from_(resolved_bucket).upload(
                path=storage_path,
                file=file,
                file_options={
                    "content-type": mime_type or "application/octet-stream",
                    "upsert": str(upsert).lower(),
                },
            )

        return storage_path

    def _create_signed_url_sync(
        self,
        bucket: StorageBucket,
        storage_path: str,
        expires_in: int,
    ) -> str:
        response = self.client.storage.from_(BUCKET_NAMES[bucket]).create_signed_url(
            storage_path,
            expires_in,
        )
        return response["signedURL"]

    def _delete_paths_sync(self, bucket: StorageBucket, paths: list[str]) -> None:
        self.client.storage.from_(BUCKET_NAMES[bucket]).remove(paths)

    def _list_paths_sync(self, bucket: StorageBucket, prefix: str) -> list[str]:
        bucket_client = self.client.storage.from_(BUCKET_NAMES[bucket])
        directory = prefix.rstrip("/")
        entries = bucket_client.list(directory)

        return [
            f"{directory}/{entry['name']}"
            for entry in entries
            if entry.get("name")
        ]


storage_service = SupabaseStorageService()
