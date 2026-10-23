"""Bounded local Piper synthesis, separate from game announcement orchestration."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from threading import Lock, RLock
from time import perf_counter

from voicechess.config import Settings
from voicechess.logging import log_event
from voicechess.tts.audio import read_validated_wav
from voicechess.tts.errors import (
    TtsError,
    TtsShutdownError,
    TtsStartupError,
    TtsStartupTimeoutError,
    TtsStorageError,
    TtsSynthesisError,
    TtsTimeoutError,
    TtsUnavailableError,
)
from voicechess.tts.models import MAX_ANNOUNCEMENT_TEXT_CHARS
from voicechess.tts.process import PiperProcess, ProcessFactory, open_piper_process
from voicechess.tts.workspace import AudioWorkspace


class PiperSynthesizer:
    """Own short-lived Piper processes; callers provide any background scheduling."""

    def __init__(
        self,
        *,
        settings: Settings,
        logger: logging.Logger,
        process_factory: ProcessFactory = open_piper_process,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._process_factory = process_factory
        self._operation_lock = Lock()
        self._state_lock = RLock()
        self._cleanup_lock = Lock()
        self._shutdown_lock = Lock()
        self._ready = False
        self._stopping = False
        self._shutdown_in_progress = False
        self._stop_complete = True
        self._active: PiperProcess | None = None
        self._model: Path | None = None
        self._sample_rate: int | None = None
        self._workspace = AudioWorkspace(audio_dir=settings.piper_audio_dir, logger=logger)

    @property
    def is_ready(self) -> bool:
        """Return preflight readiness, not a guarantee that a model will load."""
        with self._state_lock:
            return self._ready and not self._stopping

    def start(self) -> None:
        """Validate local model files and probe the executable with a deadline."""
        with self._operation_lock:
            if self.is_ready:
                return
            started_at = perf_counter()
            log_event(self._logger, logging.INFO, "piper_starting")
            try:
                with self._state_lock:
                    if self._shutdown_in_progress or self._active is not None:
                        raise TtsStartupError
                    self._stopping = False
                    self._stop_complete = False
                self._workspace.start()
                model, sample_rate = self._validate_model()
                self._run(
                    [self._settings.piper_path, "--help"],
                    text=None,
                    timeout_ms=self._settings.piper_startup_timeout_ms,
                    startup=True,
                )
                with self._state_lock:
                    if self._stopping:
                        raise TtsStartupError
                    self._model = model
                    self._sample_rate = sample_rate
                    self._ready = True
            except Exception as exc:
                error = exc if isinstance(exc, TtsStartupError) else TtsStartupError()
                log_event(
                    self._logger,
                    logging.WARNING,
                    "piper_start_failed",
                    duration_ms=(perf_counter() - started_at) * 1_000,
                    error=error,
                )
                if error is exc:
                    raise
                raise error from exc
            log_event(
                self._logger,
                logging.INFO,
                "piper_started",
                duration_ms=(perf_counter() - started_at) * 1_000,
                metadata={"sample_rate_hz": sample_rate},
            )

    def synthesize(self, text: str, *, game_id: str | None = None) -> bytes:
        """Generate one announcement synchronously; scheduling belongs to the caller."""
        with self._operation_lock:
            model, sample_rate = self._model, self._sample_rate
            if not self.is_ready or model is None or sample_rate is None:
                error: TtsError | None = TtsUnavailableError()
            elif (
                not text.strip()
                or len(text) > MAX_ANNOUNCEMENT_TEXT_CHARS
                or any(c in text for c in "\r\n\0")
            ):
                error = TtsSynthesisError()
            else:
                error = None
            if error is not None:
                log_event(
                    self._logger,
                    logging.WARNING,
                    "piper_synthesis_rejected",
                    game_id=game_id,
                    error=error,
                )
                raise error
            if model is None or sample_rate is None:
                raise TtsUnavailableError

            started_at = perf_counter()
            log_event(self._logger, logging.INFO, "piper_synthesis_started", game_id=game_id)
            try:
                with self._workspace.work_directory(game_id=game_id) as work_dir:
                    output = work_dir / "speech.partial.wav"
                    self._run(
                        [
                            self._settings.piper_path,
                            "--model",
                            str(model),
                            "--output_file",
                            str(output),
                        ],
                        text=(text.strip() + "\n").encode("utf-8"),
                        timeout_ms=self._settings.piper_synthesis_timeout_ms,
                        startup=False,
                        game_id=game_id,
                    )
                    audio = read_validated_wav(
                        output,
                        sample_rate=sample_rate,
                        channels=self._settings.piper_output_channels,
                    )
                    output.replace(output.with_name("speech.wav"))
                with self._state_lock:
                    if self._stopping:
                        raise TtsUnavailableError
            except Exception as exc:
                error = exc if isinstance(exc, TtsError) else TtsSynthesisError()
                if isinstance(error, TtsStorageError):
                    with self._state_lock:
                        self._ready = False
                log_event(
                    self._logger,
                    logging.WARNING,
                    "piper_synthesis_failed",
                    game_id=game_id,
                    duration_ms=(perf_counter() - started_at) * 1_000,
                    error=error,
                )
                if error is exc:
                    raise
                raise error from exc
            log_event(
                self._logger,
                logging.INFO,
                "piper_synthesis_completed",
                game_id=game_id,
                duration_ms=(perf_counter() - started_at) * 1_000,
                metadata={"audio_bytes": len(audio)},
            )
            return audio

    def stop(self) -> None:
        """Interrupt active work, reap the child, and wait for request cleanup."""
        with self._shutdown_lock:
            started_at = perf_counter()
            with self._state_lock:
                if self._stop_complete:
                    return
                self._ready = False
                self._stopping = True
                self._shutdown_in_progress = True
                process = self._active
            log_event(self._logger, logging.INFO, "piper_stopping")
            try:
                if process is not None:
                    self._close_process(process)
                acquired = self._operation_lock.acquire(
                    timeout=self._settings.piper_shutdown_timeout_ms / 1_000
                )
                if not acquired:
                    raise TtsShutdownError
                self._operation_lock.release()
                self._workspace.stop()
                with self._state_lock:
                    self._active = None
                    self._stop_complete = True
            except Exception as exc:
                error = exc if isinstance(exc, TtsShutdownError) else TtsShutdownError()
                log_event(
                    self._logger,
                    logging.WARNING,
                    "piper_shutdown_failed",
                    duration_ms=(perf_counter() - started_at) * 1_000,
                    error=error,
                )
                if error is exc:
                    raise
                raise error from exc
            finally:
                with self._state_lock:
                    self._shutdown_in_progress = False
            log_event(
                self._logger,
                logging.INFO,
                "piper_stopped",
                duration_ms=(perf_counter() - started_at) * 1_000,
            )

    def _validate_model(self) -> tuple[Path, int]:
        model = self._settings.piper_model_path
        if model is None:
            raise TtsStartupError
        model = model.resolve(strict=True)
        with model.open("rb") as model_file:
            if not model_file.read(1):
                raise TtsStartupError
        config_path = Path(f"{model}.json")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("audio"), dict):
            raise TtsStartupError
        sample_rate = config["audio"].get("sample_rate")
        if type(sample_rate) is not int or not 8_000 <= sample_rate <= 192_000:
            raise TtsStartupError
        expected = self._settings.piper_expected_sample_rate_hz
        if expected is not None and sample_rate != expected:
            raise TtsStartupError
        return model, sample_rate

    def _run(
        self,
        command: list[str],
        *,
        text: bytes | None,
        timeout_ms: int,
        startup: bool,
        game_id: str | None = None,
    ) -> None:
        with self._state_lock:
            if self._stopping or self._active is not None:
                raise TtsUnavailableError
            process = self._process_factory(command)
            self._active = process
        try:
            try:
                process.communicate(input=text, timeout=timeout_ms / 1_000)
            except subprocess.TimeoutExpired as exc:
                if startup:
                    raise TtsStartupTimeoutError(timeout_ms) from exc
                raise TtsTimeoutError(timeout_ms) from exc
            code = process.poll()
            with self._state_lock:
                if self._stopping:
                    raise TtsUnavailableError
            if code != 0:
                log_event(
                    self._logger,
                    logging.WARNING,
                    "piper_process_failed",
                    game_id=game_id,
                    metadata={"exit_code": code, "stage": "startup" if startup else "synthesis"},
                )
                if startup:
                    raise TtsStartupError
                raise TtsSynthesisError
        finally:
            cleaned = False
            try:
                self._close_process(process)
                cleaned = True
            finally:
                with self._state_lock:
                    if cleaned:
                        self._active = None

    def _close_process(self, process: PiperProcess) -> None:
        """Serialize cleanup and retain ownership if the child cannot be reaped."""
        timeout = self._settings.piper_shutdown_timeout_ms / 1_000
        with self._cleanup_lock:
            try:
                if process.poll() is None:
                    try:
                        process.terminate()
                        process.wait(timeout=timeout)
                    except (OSError, subprocess.TimeoutExpired):
                        process.kill()
                        process.wait(timeout=timeout)
                process.close()
            except (OSError, subprocess.TimeoutExpired) as exc:
                with self._state_lock:
                    self._ready = False
                error = TtsShutdownError()
                log_event(
                    self._logger, logging.WARNING, "piper_process_cleanup_failed", error=error
                )
                raise error from exc
