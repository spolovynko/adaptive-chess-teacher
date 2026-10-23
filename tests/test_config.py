"""Tests for configuration defaults, overrides, and validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from voicechess.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_tests_from_project_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep local developer settings from changing configuration unit tests."""
    monkeypatch.chdir(tmp_path)
    for name in (
        "PIPER_PATH",
        "PIPER_MODEL_PATH",
        "PIPER_STARTUP_TIMEOUT_MS",
        "PIPER_SYNTHESIS_TIMEOUT_MS",
        "PIPER_SHUTDOWN_TIMEOUT_MS",
        "PIPER_AUDIO_DIR",
        "PIPER_OUTPUT_FORMAT",
        "PIPER_OUTPUT_CHANNELS",
        "PIPER_EXPECTED_SAMPLE_RATE_HZ",
        "PIPER_RETENTION_POLICY",
    ):
        monkeypatch.delenv(f"VOICECHESS_{name}", raising=False)


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


def test_at_least_one_engine_search_limit_is_required() -> None:
    with pytest.raises(ValidationError, match="at least one engine search limit"):
        Settings(engine_search_depth=None, engine_move_time_ms=None)


def test_engine_move_time_must_be_shorter_than_failure_timeout() -> None:
    with pytest.raises(ValidationError, match="move time must be shorter"):
        Settings(engine_move_time_ms=1_000, engine_move_timeout_ms=1_000)


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


def test_piper_defaults_do_not_require_an_installed_model() -> None:
    settings = Settings()

    assert settings.piper_path == "piper"
    assert settings.piper_model_path is None
    assert settings.piper_startup_timeout_ms == 5_000
    assert settings.piper_synthesis_timeout_ms == 10_000
    assert settings.piper_shutdown_timeout_ms == 1_000
    assert settings.piper_audio_dir == Path("audio")
    assert settings.piper_output_format == "wav"
    assert settings.piper_output_channels == 1
    assert settings.piper_expected_sample_rate_hz is None
    assert settings.piper_retention_policy == "latest_per_game"


def test_piper_settings_can_be_overridden_through_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model = tmp_path / "voices" / "test.onnx"
    audio_dir = tmp_path / "speech-output"
    monkeypatch.setenv("VOICECHESS_PIPER_PATH", "local-piper")
    monkeypatch.setenv("VOICECHESS_PIPER_MODEL_PATH", str(model))
    monkeypatch.setenv("VOICECHESS_PIPER_STARTUP_TIMEOUT_MS", "2000")
    monkeypatch.setenv("VOICECHESS_PIPER_SYNTHESIS_TIMEOUT_MS", "3000")
    monkeypatch.setenv("VOICECHESS_PIPER_SHUTDOWN_TIMEOUT_MS", "500")
    monkeypatch.setenv("VOICECHESS_PIPER_AUDIO_DIR", str(audio_dir))
    monkeypatch.setenv("VOICECHESS_PIPER_OUTPUT_FORMAT", "wav")
    monkeypatch.setenv("VOICECHESS_PIPER_OUTPUT_CHANNELS", "1")
    monkeypatch.setenv("VOICECHESS_PIPER_EXPECTED_SAMPLE_RATE_HZ", "22050")
    monkeypatch.setenv("VOICECHESS_PIPER_RETENTION_POLICY", "latest_per_game")

    settings = Settings()

    assert settings.piper_path == "local-piper"
    assert settings.piper_model_path == model
    assert settings.piper_startup_timeout_ms == 2_000
    assert settings.piper_synthesis_timeout_ms == 3_000
    assert settings.piper_shutdown_timeout_ms == 500
    assert settings.piper_audio_dir == audio_dir
    assert settings.piper_output_format == "wav"
    assert settings.piper_output_channels == 1
    assert settings.piper_expected_sample_rate_hz == 22_050
    assert settings.piper_retention_policy == "latest_per_game"


@pytest.mark.parametrize("field", ["piper_startup_timeout_ms", "piper_synthesis_timeout_ms"])
@pytest.mark.parametrize("value", [0, 99, 120_001])
def test_piper_timeouts_must_be_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.mark.parametrize("value", [0, 99, 10_001])
def test_piper_shutdown_wait_must_be_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(piper_shutdown_timeout_ms=value)


@pytest.mark.parametrize("value", [7_999, 192_001])
def test_piper_expected_sample_rate_must_be_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(piper_expected_sample_rate_hz=value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("piper_path", "  "),
        ("piper_path", "https://example.com/piper"),
        ("piper_path", r"\\server\share\piper.exe"),
        ("piper_model_path", ""),
        ("piper_model_path", "../voice.onnx"),
        ("piper_model_path", "https://example.com/voice.onnx"),
        ("piper_model_path", r"\\server\share\voice.onnx"),
        ("piper_model_path", "voice.json"),
        ("piper_audio_dir", ""),
        ("piper_audio_dir", "../audio"),
        ("piper_audio_dir", "https://example.com/audio"),
        ("piper_audio_dir", r"\\server\share\audio"),
        ("piper_audio_dir", "."),
        ("piper_output_format", "mp3"),
        ("piper_output_channels", 2),
        ("piper_retention_policy", "keep_all"),
    ],
)
def test_invalid_piper_settings_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_piper_audio_directory_cannot_be_a_filesystem_root(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="dedicated directory"):
        Settings(piper_audio_dir=Path(tmp_path.anchor))


def test_piper_executable_whitespace_is_trimmed() -> None:
    assert Settings(piper_path="  local-piper  ").piper_path == "local-piper"
