"""Single-owner temporary audio workspace with selective crash recovery."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import BinaryIO, NoReturn
from uuid import uuid4

from voicechess.logging import log_event
from voicechess.tts.errors import TtsStorageError

if sys.platform == "win32":
    import msvcrt

    def _acquire_lease(file: BinaryIO) -> None:
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)

    def _release_lease(file: BinaryIO) -> None:
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _acquire_lease(file: BinaryIO) -> None:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release_lease(file: BinaryIO) -> None:
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


_WORK_NAME = re.compile(r"piper-[0-9a-f]{32}")
_OUTPUT_NAMES = frozenset({"speech.partial.wav", "speech.wav"})


class AudioWorkspace:
    """Own only reserved work directories; never recursively delete arbitrary paths."""

    def __init__(self, *, audio_dir: Path, logger: logging.Logger) -> None:
        self._directory = audio_dir.resolve() / "voicechess"
        self._logger = logger
        self._lock = RLock()
        self._lease: BinaryIO | None = None
        self._working = False
        self._needs_cleanup = False

    def start(self) -> None:
        """Acquire exclusive ownership, then clean known leftovers from a prior run."""
        with self._lock:
            if self._lease is not None and not self._needs_cleanup:
                return
            started_at = perf_counter()
            try:
                self._check_directory()
                self._directory.mkdir(parents=True, exist_ok=True)
                if self._lease is None:
                    lock_path = self._directory / ".lock"
                    if lock_path.is_symlink():
                        raise TtsStorageError
                    lease = lock_path.open("a+b")
                    try:
                        if lock_path.stat().st_size == 0:
                            lease.write(b"\0")
                            lease.flush()
                        _acquire_lease(lease)
                    except BaseException:
                        lease.close()
                        raise
                    self._lease = lease
                removed = 0
                try:
                    for path in self._directory.iterdir():
                        if _WORK_NAME.fullmatch(path.name):
                            self._remove_work_directory(path)
                            removed += 1
                    self._needs_cleanup = False
                except BaseException:
                    self._close_lease()
                    raise
            except (OSError, TtsStorageError) as exc:
                self._raise_failure(
                    "audio_workspace_start_failed",
                    exc,
                    duration_ms=(perf_counter() - started_at) * 1_000,
                )
            log_event(
                self._logger,
                logging.INFO,
                "audio_workspace_ready",
                duration_ms=(perf_counter() - started_at) * 1_000,
                metadata={"removed_work_directories": removed},
            )

    @contextmanager
    def work_directory(self, *, game_id: str | None = None) -> Iterator[Path]:
        """Provide one private directory, cleaning only this request's known files."""
        with self._lock:
            try:
                if self._lease is None or self._working or self._needs_cleanup:
                    raise TtsStorageError
                self._check_directory()
                path = self._directory / f"piper-{uuid4().hex}"
                path.mkdir()
                self._working = True
            except (OSError, TtsStorageError) as exc:
                self._raise_failure("audio_work_directory_failed", exc)
        try:
            log_event(
                self._logger,
                logging.INFO,
                "audio_work_started",
                game_id=game_id,
                metadata={"work_id": path.name.removeprefix("piper-")},
            )
            yield path
        finally:
            cleanup_started_at = perf_counter()
            with self._lock:
                try:
                    self._remove_work_directory(path)
                except (OSError, TtsStorageError) as exc:
                    self._needs_cleanup = True
                    self._raise_failure(
                        "audio_workspace_cleanup_failed",
                        exc,
                        game_id=game_id,
                        duration_ms=(perf_counter() - cleanup_started_at) * 1_000,
                    )
                finally:
                    self._working = False
            log_event(
                self._logger,
                logging.INFO,
                "audio_work_cleaned",
                game_id=game_id,
                duration_ms=(perf_counter() - cleanup_started_at) * 1_000,
                metadata={"work_id": path.name.removeprefix("piper-")},
            )

    def stop(self) -> None:
        """Release ownership only after active synthesis has finished cleaning up."""
        with self._lock:
            try:
                if self._working:
                    raise TtsStorageError
                self._close_lease()
            except (OSError, TtsStorageError) as exc:
                self._raise_failure("audio_workspace_stop_failed", exc)

    def _check_directory(self) -> None:
        if (
            self._directory.is_symlink()
            or self._directory.is_junction()
            or self._directory.resolve() != self._directory
        ):
            raise TtsStorageError

    def _remove_work_directory(self, path: Path) -> None:
        self._check_directory()
        if (
            path.parent != self._directory
            or not _WORK_NAME.fullmatch(path.name)
            or path.is_symlink()
            or path.is_junction()
            or not path.is_dir()
        ):
            raise TtsStorageError
        entries = list(path.iterdir())
        if any(
            entry.name not in _OUTPUT_NAMES or entry.is_dir() or entry.is_junction()
            for entry in entries
        ):
            raise TtsStorageError
        for entry in entries:
            entry.unlink()
        path.rmdir()

    def _close_lease(self) -> None:
        lease = self._lease
        if lease is not None:
            try:
                _release_lease(lease)
            finally:
                lease.close()
                self._lease = None

    def _raise_failure(
        self,
        event: str,
        cause: BaseException,
        *,
        game_id: str | None = None,
        duration_ms: float | None = None,
    ) -> NoReturn:
        error = TtsStorageError()
        log_event(
            self._logger,
            logging.WARNING,
            event,
            game_id=game_id,
            duration_ms=duration_ms,
            error=error,
        )
        raise error from cause
