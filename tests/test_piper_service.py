"""Deterministic Piper boundary tests without an installed engine or real model."""

from __future__ import annotations

import io
import json
import logging
import subprocess
import sys
import wave
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from voicechess.config import Settings
from voicechess.logging import configure_logging, reset_logging
from voicechess.tts import (
    PiperSynthesizer,
    TtsOutputValidationError,
    TtsShutdownError,
    TtsStartupError,
    TtsStartupTimeoutError,
    TtsStorageError,
    TtsSynthesisError,
    TtsTimeoutError,
    TtsUnavailableError,
)
from voicechess.tts.audio import read_validated_wav
from voicechess.tts.process import PiperProcess, open_piper_process


def wav_audio(*, channels: int = 1, rate: int = 22_050, width: int = 2, frames: int = 64) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(b"\0" * channels * width * frames)
    return buffer.getvalue()


class FakePiperProcess:
    def __init__(self) -> None:
        self.code: int | None = None
        self.exit_code = 0
        self.error: Exception | None = None
        self.inputs: list[tuple[bytes | None, float | None]] = []
        self.kill_calls = 0
        self.terminate_calls = 0
        self.close_calls = 0
        self.ignore_terminate = False
        self.kill_error: Exception | None = None
        self.close_error: Exception | None = None
        self.block = False
        self.entered = Event()
        self.released = Event()
        self.output: bytes | None = wav_audio()
        self.command: list[str] = []

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes | None, bytes | None]:
        self.inputs.append((input, timeout))
        self.entered.set()
        if self.block:
            if not self.released.wait(timeout=2):
                raise subprocess.TimeoutExpired("fake piper", timeout)
            return None, None
        if self.error is not None:
            raise self.error
        if "--output_file" in self.command and self.output is not None:
            output = Path(self.command[self.command.index("--output_file") + 1])
            output.write_bytes(self.output)
        self.code = self.exit_code
        return None, None

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self.ignore_terminate:
            self.code = -15
            self.released.set()

    def kill(self) -> None:
        self.kill_calls += 1
        if self.kill_error is not None:
            raise self.kill_error
        self.code = -9
        self.released.set()

    def wait(self, timeout: float | None = None) -> int:
        if self.code is None:
            raise subprocess.TimeoutExpired("fake piper", timeout)
        return self.code

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


class FakeProcessFactory:
    def __init__(self) -> None:
        self.process = FakePiperProcess()
        self.error: Exception | None = None
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> FakePiperProcess:
        self.commands.append(list(command))
        if self.error is not None:
            raise self.error
        self.process.code = None
        self.process.command = list(command)
        return self.process


@dataclass
class PiperContext:
    settings: Settings
    logger: logging.Logger
    factory: FakeProcessFactory
    service: PiperSynthesizer

    def work_files(self) -> list[Path]:
        directory = self.settings.piper_audio_dir / "voicechess"
        return list(directory.glob("piper-*"))

    def events(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.settings.log_destination.read_text(encoding="utf-8").splitlines()
        ]


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[PiperContext]:
    monkeypatch.chdir(tmp_path)
    model = tmp_path / "voice with spaces.onnx"
    model.write_bytes(b"fake model; preflight does not load ONNX")
    Path(f"{model}.json").write_text('{"audio":{"sample_rate":22050}}', encoding="utf-8")
    settings = Settings(
        piper_path="fake piper",
        piper_model_path=model,
        piper_audio_dir=tmp_path / "audio",
        log_destination=tmp_path / "test.jsonl",
    )
    logger = configure_logging(settings)
    factory = FakeProcessFactory()
    service = PiperSynthesizer(settings=settings, logger=logger, process_factory=factory)
    yield PiperContext(settings, logger, factory, service)
    factory.process.kill_error = None
    factory.process.close_error = None
    service.stop()
    reset_logging(logger)


def test_start_is_bounded_and_idempotent(context: PiperContext) -> None:
    context.service.start()
    context.service.start()

    assert context.service.is_ready
    assert context.factory.commands == [["fake piper", "--help"]]
    assert context.factory.process.inputs == [(None, 5.0)]
    events = context.events()
    assert [event["event"] for event in events if str(event["event"]).startswith("piper_")] == [
        "piper_starting",
        "piper_started",
    ]
    assert events[-1]["duration_ms"] >= 0


@pytest.mark.parametrize("problem", ["unset", "missing", "empty", "directory", "missing_config"])
def test_model_files_are_required_before_process_start(
    context: PiperContext, tmp_path: Path, problem: str
) -> None:
    model = context.settings.piper_model_path
    assert model is not None
    if problem == "unset":
        context.settings.piper_model_path = None
    elif problem == "missing":
        model.unlink()
    elif problem == "empty":
        model.write_bytes(b"")
    elif problem == "directory":
        context.settings.piper_model_path = tmp_path
    else:
        Path(f"{model}.json").unlink()

    with pytest.raises(TtsStartupError):
        context.service.start()
    assert not context.service.is_ready
    assert context.factory.commands == []


@pytest.mark.parametrize(
    "config",
    [
        "{",
        "[]",
        "{}",
        '{"audio":null}',
        '{"audio":{"sample_rate":true}}',
        '{"audio":{"sample_rate":0}}',
        '{"audio":{"sample_rate":"22050"}}',
    ],
)
def test_invalid_model_config_is_controlled(context: PiperContext, config: str) -> None:
    Path(f"{context.settings.piper_model_path}.json").write_text(config, encoding="utf-8")
    with pytest.raises(TtsStartupError):
        context.service.start()
    assert context.factory.commands == []


def test_expected_sample_rate_must_match_model(context: PiperContext) -> None:
    context.settings.piper_expected_sample_rate_hz = 16_000
    with pytest.raises(TtsStartupError):
        context.service.start()
    assert context.factory.commands == []


@pytest.mark.parametrize(
    "failure", [FileNotFoundError("private path"), PermissionError("private path")]
)
def test_process_start_failure_is_safe(context: PiperContext, failure: Exception) -> None:
    context.factory.error = failure
    with pytest.raises(TtsStartupError) as caught:
        context.service.start()
    assert "private" not in str(caught.value)
    assert "private" not in context.settings.log_destination.read_text(encoding="utf-8")
    assert context.events()[-1]["event"] == "piper_start_failed"
    assert not context.service.is_ready


def test_failed_start_can_be_retried(context: PiperContext) -> None:
    context.factory.process.exit_code = 1
    with pytest.raises(TtsStartupError):
        context.service.start()
    assert not context.service.is_ready
    context.factory.process.exit_code = 0
    context.service.start()
    assert context.service.is_ready


def test_startup_timeout_is_controlled_and_reaps_process(context: PiperContext) -> None:
    context.factory.process.error = subprocess.TimeoutExpired("fake piper", 5)
    with pytest.raises(TtsStartupTimeoutError) as caught:
        context.service.start()
    assert caught.value.timeout_ms == 5_000
    assert not context.service.is_ready
    assert context.factory.process.terminate_calls == 1


def test_synthesis_uses_stdin_and_isolated_local_output(context: PiperContext) -> None:
    context.service.start()
    audio = context.service.synthesize("Black plays knight f6.", game_id="game-1")

    assert audio == wav_audio()
    command = context.factory.commands[-1]
    assert command[:3] == ["fake piper", "--model", str(context.settings.piper_model_path)]
    assert "Black plays knight f6." not in command
    assert context.factory.process.inputs[-1] == (b"Black plays knight f6.\n", 10.0)
    assert context.work_files() == []
    events = context.events()
    assert any(event["event"] == "piper_synthesis_started" for event in events)
    assert events[-1]["event"] == "piper_synthesis_completed"
    assert events[-1]["game_id"] == "game-1"
    assert events[-1]["duration_ms"] >= 0


def test_synthesis_before_start_is_controlled(context: PiperContext) -> None:
    with pytest.raises(TtsUnavailableError):
        context.service.synthesize("Black plays knight f6.")
    assert context.factory.commands == []


@pytest.mark.parametrize("text", ["", "  ", "move\nquit", "move\rquit", "move\0", "a" * 4097])
def test_invalid_speech_input_never_starts_a_process(context: PiperContext, text: str) -> None:
    context.service.start()
    with pytest.raises(TtsSynthesisError):
        context.service.synthesize(text)
    assert len(context.factory.commands) == 1


def test_synthesis_timeout_is_controlled_and_cleans_output(context: PiperContext) -> None:
    context.service.start()
    context.factory.process.error = subprocess.TimeoutExpired("fake piper", 10)
    with pytest.raises(TtsTimeoutError) as caught:
        context.service.synthesize("Black plays knight f6.")
    assert caught.value.timeout_ms == 10_000
    assert context.factory.process.terminate_calls == 1
    assert context.work_files() == []


@pytest.mark.parametrize("failure", ["spawn", "exit", "stdin"])
def test_synthesis_process_failures_are_controlled(context: PiperContext, failure: str) -> None:
    context.service.start()
    if failure == "spawn":
        context.factory.error = FileNotFoundError("private local path")
    elif failure == "exit":
        context.factory.process.exit_code = 1
    else:
        context.factory.process.error = BrokenPipeError("private local path")
    with pytest.raises(TtsSynthesisError):
        context.service.synthesize("Black plays knight f6.", game_id="game-1")
    assert context.work_files() == []
    assert context.events()[-1]["event"] == "piper_synthesis_failed"
    assert "private local path" not in context.settings.log_destination.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "output",
    [
        None,
        b"",
        b"not a WAV",
        wav_audio(frames=0),
        wav_audio(channels=2),
        wav_audio(rate=16_000),
        wav_audio(width=1),
        wav_audio()[:-1],
    ],
)
def test_missing_or_invalid_wav_is_rejected_and_cleaned(
    context: PiperContext, output: bytes | None
) -> None:
    context.service.start()
    context.factory.process.output = output
    with pytest.raises(TtsOutputValidationError):
        context.service.synthesize("Black plays knight f6.")
    assert context.work_files() == []
    assert context.events()[-1]["event"] == "piper_synthesis_failed"


def test_oversized_wav_is_rejected(context: PiperContext, monkeypatch: pytest.MonkeyPatch) -> None:
    context.service.start()
    monkeypatch.setattr("voicechess.tts.audio.MAX_AUDIO_BYTES", 64)
    with pytest.raises(TtsOutputValidationError):
        context.service.synthesize("Black plays knight f6.")
    assert context.work_files() == []


def test_validation_failure_does_not_poison_a_later_synthesis(context: PiperContext) -> None:
    context.service.start()
    context.factory.process.output = b"bad audio"
    with pytest.raises(TtsOutputValidationError):
        context.service.synthesize("Black plays knight f6.")
    context.factory.process.output = wav_audio()
    assert context.service.synthesize("Black plays pawn to e5.") == wav_audio()


def test_stop_is_idempotent_and_start_can_restart(context: PiperContext) -> None:
    context.service.start()
    context.service.stop()
    context.service.stop()
    assert not context.service.is_ready
    with pytest.raises(TtsUnavailableError):
        context.service.synthesize("Black plays knight f6.")
    context.service.start()
    assert context.service.synthesize("Black plays knight f6.") == wav_audio()


@pytest.mark.parametrize("stage", ["startup", "synthesis"])
def test_stop_interrupts_active_work_without_waiting_for_operation_timeout(
    context: PiperContext, stage: str
) -> None:
    process = context.factory.process
    if stage == "synthesis":
        context.service.start()
    process.entered.clear()
    process.block = True
    with ThreadPoolExecutor(max_workers=1) as worker:
        task = worker.submit(
            context.service.start
            if stage == "startup"
            else lambda: context.service.synthesize("Black plays knight f6.")
        )
        assert process.entered.wait(timeout=2)
        context.service.stop()
        with pytest.raises(TtsStartupError if stage == "startup" else TtsUnavailableError):
            task.result(timeout=2)

    assert not context.service.is_ready
    assert process.terminate_calls == 1
    assert process.close_calls >= 1
    assert context.work_files() == []
    assert not any(event["event"] == "piper_synthesis_completed" for event in context.events())


def test_timeout_forces_kill_when_termination_is_ignored(context: PiperContext) -> None:
    context.service.start()
    process = context.factory.process
    process.ignore_terminate = True
    process.error = subprocess.TimeoutExpired("fake piper", 10)
    with pytest.raises(TtsTimeoutError):
        context.service.synthesize("Black plays knight f6.")
    assert process.kill_calls == 1
    assert process.close_calls == 2  # Startup probe plus synthesis.


def test_cleanup_failure_retains_ownership_for_shutdown_retry(context: PiperContext) -> None:
    context.service.start()
    process = context.factory.process
    process.ignore_terminate = True
    process.error = subprocess.TimeoutExpired("fake piper", 10)
    process.kill_error = PermissionError("private local path")
    with pytest.raises(TtsShutdownError):
        context.service.synthesize("Black plays knight f6.")
    assert not context.service.is_ready
    with pytest.raises(TtsShutdownError):
        context.service.stop()
    assert context.events()[-1]["event"] == "piper_shutdown_failed"
    with pytest.raises(TtsStartupError):
        context.service.start()
    assert len(context.factory.commands) == 2
    process.kill_error = None
    context.service.stop()
    assert process.code == -9
    assert "private local path" not in context.settings.log_destination.read_text(encoding="utf-8")


def test_pipe_close_failure_can_be_retried_during_stop(context: PiperContext) -> None:
    context.service.start()
    context.factory.process.close_error = OSError("private local path")
    with pytest.raises(TtsShutdownError):
        context.service.synthesize("Black plays knight f6.")
    with pytest.raises(TtsShutdownError):
        context.service.stop()
    context.factory.process.close_error = None
    context.service.stop()
    assert context.events()[-1]["event"] == "piper_stopped"


def test_unrelated_output_is_preserved(context: PiperContext) -> None:
    context.settings.piper_audio_dir.mkdir()
    unrelated = context.settings.piper_audio_dir / "do-not-delete.txt"
    unrelated.write_text("keep me", encoding="utf-8")
    context.service.start()
    context.service.synthesize("Black plays knight f6.")
    context.service.stop()
    assert unrelated.is_file()
    assert context.work_files() == []
    assert unrelated.read_text(encoding="utf-8") == "keep me"


def test_native_model_sample_rate_is_used_without_resampling(context: PiperContext) -> None:
    Path(f"{context.settings.piper_model_path}.json").write_text(
        '{"audio":{"sample_rate":16000}}', encoding="utf-8"
    )
    context.factory.process.output = wav_audio(rate=16_000)
    context.service.start()
    assert context.service.synthesize("Black plays knight f6.") == wav_audio(rate=16_000)


def test_nonregular_output_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TtsOutputValidationError):
        read_validated_wav(tmp_path, sample_rate=22_050, channels=1)


def test_atomic_publish_failure_is_controlled_and_cleans_partial_audio(
    context: PiperContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    context.service.start()

    def fail_replace(self: Path, target: Path) -> Path:
        raise PermissionError("private local path")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(TtsSynthesisError):
        context.service.synthesize("Black plays knight f6.")
    assert context.work_files() == []


def test_output_directory_failure_is_controlled(context: PiperContext) -> None:
    context.settings.piper_audio_dir.write_text("not a directory", encoding="utf-8")
    with pytest.raises(TtsStartupError):
        context.service.start()
    assert len(context.factory.commands) == 0


def test_utf8_text_is_sent_as_data(context: PiperContext) -> None:
    context.service.start()
    text = "Black's pawn — promotes to queen."
    context.service.synthesize(text)
    assert context.factory.process.inputs[-1][0] == (text + "\n").encode("utf-8")


@pytest.mark.parametrize(
    ("text", "error_type"),
    [
        ("Black plays knight f6.", None),
        ("fail", TtsSynthesisError),
        ("corrupt", TtsOutputValidationError),
        ("timeout", TtsTimeoutError),
    ],
)
def test_real_subprocess_adapter_with_fake_tts_cli(
    context: PiperContext, text: str, error_type: type[Exception] | None
) -> None:
    fake_script = Path(__file__).parent / "fakes" / "piper.py"

    def factory(command: Sequence[str]) -> PiperProcess:
        return open_piper_process([sys.executable, str(fake_script), *command[1:]])

    context.settings.piper_synthesis_timeout_ms = 500 if text == "timeout" else 5_000
    service = PiperSynthesizer(
        settings=context.settings, logger=context.logger, process_factory=factory
    )
    try:
        service.start()
        if error_type is None:
            with wave.open(io.BytesIO(service.synthesize(text)), "rb") as wav:
                assert wav.readframes(1) == len((text + "\n").encode()).to_bytes(2, "little")
        else:
            with pytest.raises(error_type):
                service.synthesize(text)
        assert context.work_files() == []
    finally:
        service.stop()


def test_shutdown_cleanup_timeout_is_retryable_after_worker_finishes(
    context: PiperContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    context.service.start()
    context.settings.piper_shutdown_timeout_ms = 100
    entered = Event()
    released = Event()

    def slow_validation(path: Path, *, sample_rate: int, channels: int) -> bytes:
        entered.set()
        assert released.wait(timeout=2)
        return read_validated_wav(path, sample_rate=sample_rate, channels=channels)

    monkeypatch.setattr("voicechess.tts.service.read_validated_wav", slow_validation)
    with ThreadPoolExecutor(max_workers=1) as worker:
        task = worker.submit(context.service.synthesize, "Black plays knight f6.")
        assert entered.wait(timeout=2)
        try:
            with pytest.raises(TtsShutdownError):
                context.service.stop()
        finally:
            released.set()
        with pytest.raises(TtsUnavailableError):
            task.result(timeout=2)
    context.service.stop()
    assert context.events()[-1]["event"] == "piper_stopped"
    assert context.work_files() == []


def test_cleanup_failure_blocks_synthesis_until_explicit_start_retry(
    context: PiperContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    context.service.start()

    def fail_unlink(path: Path, missing_ok: bool = False) -> None:
        raise PermissionError("private local path")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(TtsStorageError):
            context.service.synthesize("Black plays knight f6.")
        assert not context.service.is_ready
        with pytest.raises(TtsUnavailableError):
            context.service.synthesize("Black plays pawn to e5.")
        assert len(context.work_files()) == 1
    context.service.start()
    assert context.service.synthesize("Black plays pawn to e5.") == wav_audio()
    assert context.work_files() == []
