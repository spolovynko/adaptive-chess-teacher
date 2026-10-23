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

    piper_path: str = Field(default="piper", min_length=1)
    piper_model_path: Path | None = None
    piper_startup_timeout_ms: int = Field(default=5_000, ge=100, le=120_000)
    piper_synthesis_timeout_ms: int = Field(default=10_000, ge=100, le=120_000)
    piper_audio_dir: Path = Path("audio")
    piper_output_format: Literal["wav"] = "wav"
    piper_output_channels: int = Field(default=1, ge=1, le=1)
    piper_expected_sample_rate_hz: int | None = Field(default=None, ge=8_000, le=192_000)
    piper_retention_policy: Literal["latest_per_game"] = "latest_per_game"

    pgn_export_dir: Path = Path("exports")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_destination: Path = Path("logs/voicechess.jsonl")

    # Reserved for later phases.
    whisper_model_name: str = "base.en"
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

    @field_validator("piper_path")
    @classmethod
    def piper_executable_must_be_local(cls, value: str) -> str:
        """Require a nonempty executable name or local path, not a URL."""
        value = value.strip()
        if not value or "://" in value or value.startswith(("\\\\", "//")):
            raise ValueError("piper_path must be a local executable name or path.")
        return value

    @field_validator("piper_model_path", "piper_audio_dir", mode="before")
    @classmethod
    def piper_paths_must_be_local(cls, value: object) -> object:
        """Reject empty paths, URLs, and parent traversal in Piper locations."""
        if value is None:
            return value
        if isinstance(value, str | Path) and (
            not str(value).strip() or "://" in str(value) or str(value).startswith(("\\\\", "//"))
        ):
            raise ValueError("Piper paths must be nonempty local paths.")
        if isinstance(value, str | Path) and ".." in Path(value).parts:
            raise ValueError("Piper paths must not contain parent traversal.")
        return value

    @field_validator("piper_model_path")
    @classmethod
    def piper_model_must_be_onnx(cls, value: Path | None) -> Path | None:
        """Keep the optional model setting specific to a local ONNX model file."""
        if value is not None and value.suffix.lower() != ".onnx":
            raise ValueError("piper_model_path must be an ONNX model file.")
        return value

    @field_validator("piper_audio_dir")
    @classmethod
    def piper_audio_dir_must_be_dedicated(cls, value: Path) -> Path:
        """Avoid using a filesystem root or working directory for temporary audio."""
        resolved = value.resolve()
        if resolved == Path(resolved.anchor) or resolved == Path.cwd().resolve():
            raise ValueError("piper_audio_dir must be a dedicated directory.")
        return value

    @model_validator(mode="after")
    def engine_search_must_be_bounded(self) -> Self:
        """Require a normal search bound in addition to the failure timeout."""
        if self.engine_search_depth is None and self.engine_move_time_ms is None:
            message = "Configure at least one engine search limit: depth or move time."
            raise ValueError(message)
        if (
            self.engine_move_time_ms is not None
            and self.engine_move_time_ms >= self.engine_move_timeout_ms
        ):
            message = "Engine move time must be shorter than the engine move timeout."
            raise ValueError(message)
        return self

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
