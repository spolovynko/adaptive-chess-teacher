"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated settings for the local Voice Chess Coach application.

    Environment variables use the ``VOICECHESS_`` prefix. For example,
    ``VOICECHESS_STOCKFISH_PATH`` overrides ``stockfish_path``.
    """

    model_config = SettingsConfigDict(
        env_prefix="VOICECHESS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)

    stockfish_path: str = "stockfish"
    stockfish_skill_level: int = Field(default=5, ge=0, le=20)
    engine_search_depth: int | None = Field(default=8, ge=1, le=40)
    engine_move_time_ms: int | None = Field(default=None, ge=10, le=120_000)
    engine_startup_timeout_ms: int = Field(default=5_000, ge=100, le=120_000)
    engine_move_timeout_ms: int = Field(default=10_000, ge=100, le=120_000)

    pgn_export_dir: Path = Path("exports")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_destination: Path = Path("logs/voicechess.jsonl")

    # Reserved for later phases. These settings are intentionally unused in Phase 0.
    whisper_model_name: str = "base.en"
    piper_voice_name: str = "en_US-lessac-medium"
    local_llm_model_name: str = ""
    coaching_inaccuracy_threshold_cp: int = Field(default=50, ge=1)
    coaching_mistake_threshold_cp: int = Field(default=100, ge=1)
    coaching_blunder_threshold_cp: int = Field(default=200, ge=1)

    @field_validator("app_host")
    @classmethod
    def app_host_must_be_local(cls, value: str) -> str:
        """Keep this Phase 0 application accessible only from the local machine."""
        normalized = value.strip().lower()
        allowed_hosts = {"127.0.0.1", "localhost", "::1"}
        if normalized not in allowed_hosts:
            message = "app_host must be a local address: 127.0.0.1, localhost, or ::1."
            raise ValueError(message)
        return normalized

    @model_validator(mode="after")
    def coaching_thresholds_must_increase(self) -> Self:
        """Reserve a sensible classification order for the future coaching phase."""
        thresholds = (
            self.coaching_inaccuracy_threshold_cp,
            self.coaching_mistake_threshold_cp,
            self.coaching_blunder_threshold_cp,
        )
        if thresholds != tuple(sorted(thresholds)) or len(set(thresholds)) != len(thresholds):
            message = "Coaching thresholds must strictly increase: inaccuracy < mistake < blunder."
            raise ValueError(message)
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one cached settings instance for the application process."""
    return Settings()
