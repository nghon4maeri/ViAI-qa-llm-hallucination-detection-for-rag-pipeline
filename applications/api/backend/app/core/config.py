# applications/api/backend/app/core/config.py
import os
from typing import List, Union

from pathlib import Path

from dotenv import load_dotenv

# backend/.env (local secrets such as HF_TOKEN), whatever the working directory; real env vars win
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# The checkout root is the first parent holding dvc.yaml; inside a container there is none
_REPO_ROOT = next((p for p in Path(__file__).resolve().parents if (p / "dvc.yaml").exists()), None)

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
    # Repo checkout: <repo>/artifacts/models. Container: /app/models (MODELS_DIR, or "models" under WORKDIR /app)
    MODELS_DIR: str = os.getenv("MODELS_DIR", str(_REPO_ROOT / "artifacts" / "models") if _REPO_ROOT else "models")
    LGBM_MODEL_DIR: str = os.getenv("LGBM_MODEL_DIR", "")  # default: <MODELS_DIR>/lgbm
    PHOBERT_MODEL: str = os.getenv("PHOBERT_MODEL", "vinai/phobert-base")
    PHOBERT_TOKENIZER: str = os.getenv("PHOBERT_TOKENIZER", os.getenv("PHOBERT_MODEL", "vinai/phobert-base"))
    NLI_MODEL_NAME: str = os.getenv("NLI_MODEL_NAME", "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli")
    NER_MODEL_NAME: str = os.getenv("NER_MODEL_NAME", "undertheseanlp/vietnamese-ner-v1.4.0a2")
    NER_FALLBACK_MODEL: str = os.getenv("NER_FALLBACK_MODEL", "NlpHUST/ner-bert-base")
    # Source of the 3 prob_* LightGBM features (training used precomputed Vistral probabilities)
    LLM_FEATURE_MODEL: str = os.getenv("LLM_FEATURE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
    HF_TOKEN: str = os.getenv("HF_TOKEN", "")

    # Tier 2 judge agent (Claude). The API key is read by the SDK (ANTHROPIC_API_KEY), never stored here.
    # Cheapest current model by default (cost-first decision, 2026-11-25). Raise to claude-sonnet-5-5 /
    # claude-opus-5-5 or effort medium/high if the ViMedHallu benchmark shows Haiku misses too much.
    JUDGE_MODEL: str = os.getenv("JUDGE_MODEL", "claude-haiku-5-5")
    JUDGE_EFFORT: str = os.getenv("JUDGE_EFFORT", "low")
    JUDGE_MAX_STEPS: int = int(os.getenv("JUDGE_MAX_STEPS", "8"))
    # Escalate a RAG audit when any Tier 1 claim is below this confidence or a guardrail overrode LightGBM
    JUDGE_ESCALATE_BELOW: float = float(os.getenv("JUDGE_ESCALATE_BELOW", "0.75"))
    # Off by default: every escalation is a paid API call
    JUDGE_AUTO_ESCALATE: bool = os.getenv("JUDGE_AUTO_ESCALATE", "false").lower() == "true"

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
