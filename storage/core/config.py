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
    embedding_dimension: int = Field(512, alias="EMBEDDING_DIMENSION")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    """Load and cache storage-layer settings from environment variables.

    Returns:
        Settings: Parsed configuration including ``DATABASE_URL`` and embedding dimension.
    """
    return Settings()


settings = get_settings()
