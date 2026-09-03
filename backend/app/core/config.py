import os
from functools import lru_cache
from typing import Literal, List

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field

    class Settings(BaseSettings):
        app_name: str = "AQUAVIGIL Intelligence API"
        app_mode: Literal["DEMO", "LIVE", "PIPELINE_OFFLINE"] = os.getenv("OCEANTRACE_DATA_MODE", "PIPELINE_OFFLINE")
        api_v1_prefix: str = "/api/v1"
        database_url: str = Field(
            default="postgresql+psycopg://aquavigil:aquavigil@localhost:5432/aquavigil",
            validation_alias="DATABASE_URL",
        )
        cors_origins_raw: str = Field(default="http://localhost:5173,http://127.0.0.1:5173")

        model_config = SettingsConfigDict(
            env_file=os.path.join(os.path.dirname(__file__), "..", "..", ".env"),
            env_file_encoding="utf-8",
            extra="ignore",
        )

        @property
        def cors_origins(self) -> list[str]:
            return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

except Exception:
    # Safe fallback using standard Pydantic / os.environ
    from pydantic import BaseModel, Field

    class Settings(BaseModel):
        app_name: str = os.getenv("APP_NAME", "AQUAVIGIL Intelligence API")
        app_mode: Literal["DEMO", "LIVE", "PIPELINE_OFFLINE"] = os.getenv("OCEANTRACE_DATA_MODE", os.getenv("APP_MODE", "PIPELINE_OFFLINE"))
        api_v1_prefix: str = os.getenv("API_V1_PREFIX", "/api/v1")
        database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://aquavigil:aquavigil@localhost:5432/aquavigil")
        cors_origins_raw: str = os.getenv("CORS_ORIGINS_RAW", "http://localhost:5173,http://127.0.0.1:5173")

        @property
        def cors_origins(self) -> list[str]:
            return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
