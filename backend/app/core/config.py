# backend/app/core/config.py
import os
from typing import List, Union

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    _USE_PYDANTIC_SETTINGS = True
except ImportError:
    from pydantic import BaseModel as BaseSettings
    SettingsConfigDict = None
    _USE_PYDANTIC_SETTINGS = False


class Settings(BaseSettings):
    PROJECT_NAME: str = "Vietnamese AI Response QA"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://user:password@localhost:5432/viai_qa"
    )
    DB_ECHO: bool = os.getenv("DB_ECHO", "false").lower() == "true"

    # Default Project
    DEFAULT_PROJECT_NAME: str = "Default Workspace"
    DEFAULT_PROJECT_SLUG: str = "default-workspace"

    # Model Serving
    DISABLE_MODEL: bool = os.getenv("DISABLE_MODEL", "false").lower() == "true"
    MODEL_VERSION: str = os.getenv("MODEL_VERSION", "1.0.0")
    MODEL_PATH: str = os.getenv("MODEL_PATH", "models/phobert_finetuned_model")
    LGBM_MODEL_PATH: str = os.getenv("LGBM_MODEL_PATH", "models/lgbm/fold_0.txt")

    # Observability & Tracing (Explicitly disabled by default for local development)
    ENABLE_TRACING: bool = os.getenv("ENABLE_TRACING", "false").lower() == "true"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://localhost:4317"
    )
    OTEL_SERVICE_NAME: str = "viai-qa-backend"

    # Security
    DEV_API_KEY: str = os.getenv("DEV_API_KEY", "vihallu-dev-key-local")
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "*")

    if _USE_PYDANTIC_SETTINGS:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )


settings = Settings()
