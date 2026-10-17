"""Tests for configuration defaults, overrides, and validation."""

import pytest
from pydantic import ValidationError

from voicechess.config import Settings, get_settings


def test_defaults_are_local_and_ready_for_phase_zero() -> None:
    settings = Settings()

    assert settings.app_host == "127.0.0.1"
    assert settings.app_port == 8000
    assert settings.stockfish_path == "stockfish"
    assert settings.stockfish_skill_level == 5
    assert settings.engine_search_depth == 8
    assert settings.pgn_export_dir.name == "exports"


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICECHESS_STOCKFISH_PATH", r"C:\\tools\\stockfish.exe")
    monkeypatch.setenv("VOICECHESS_STOCKFISH_SKILL_LEVEL", "12")
    monkeypatch.setenv("VOICECHESS_ENGINE_MOVE_TIME_MS", "750")
    monkeypatch.setenv("VOICECHESS_PGN_EXPORT_DIR", "game_exports")

    settings = Settings()

    assert settings.stockfish_path == r"C:\\tools\\stockfish.exe"
    assert settings.stockfish_skill_level == 12
    assert settings.engine_move_time_ms == 750
    assert settings.pgn_export_dir.name == "game_exports"


def test_invalid_engine_skill_level_is_rejected() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 20"):
        Settings(stockfish_skill_level=21)


def test_non_local_host_is_rejected() -> None:
    with pytest.raises(ValidationError, match="local address"):
        Settings(app_host="0.0.0.0")


def test_coaching_thresholds_must_strictly_increase() -> None:
    with pytest.raises(ValidationError, match="strictly increase"):
        Settings(coaching_inaccuracy_threshold_cp=100, coaching_mistake_threshold_cp=100)


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("VOICECHESS_APP_PORT", "8123")

    first = get_settings()
    second = get_settings()

    assert first is second
    assert first.app_port == 8123
    get_settings.cache_clear()
