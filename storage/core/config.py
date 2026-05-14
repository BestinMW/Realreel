from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the storage/database layer.

    Railway should provide these values as environment variables. During local
    development, the same names can be placed in a root `.env` file.
    """

    database_url: str = Field(
        ...,
        alias="DATABASE_URL",
        description="Async SQLAlchemy URL, e.g. postgresql+asyncpg://...",
    )
    supabase_url: str = Field(..., alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(..., alias="SUPABASE_SERVICE_ROLE_KEY")

    embedding_dimension: int = Field(512, alias="EMBEDDING_DIMENSION")
    signed_url_ttl_seconds: int = Field(900, alias="SIGNED_URL_TTL_SECONDS")

    raw_videos_bucket: str = Field("raw-videos", alias="RAW_VIDEOS_BUCKET")
    transcripts_bucket: str = Field("transcripts", alias="TRANSCRIPTS_BUCKET")
    thumbnails_bucket: str = Field("thumbnails", alias="THUMBNAILS_BUCKET")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
