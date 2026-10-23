"""Injectable, shell-free process boundary for the local Piper executable."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from typing import Protocol


class PiperProcess(Protocol):
    """Subprocess operations needed by the Piper synthesizer."""

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes | None, bytes | None]:
        """Send text, close stdin, and wait for completion."""

    def poll(self) -> int | None:
        """Return the exit code, or None while running."""

    def terminate(self) -> None:
        """Request process termination."""

    def kill(self) -> None:
        """Force process termination."""

    def wait(self, timeout: float | None = None) -> int:
        """Wait for process exit within a deadline."""

    def close(self) -> None:
        """Close owned pipes after the child has exited."""


ProcessFactory = Callable[[Sequence[str]], PiperProcess]


def open_piper_process(command: Sequence[str]) -> PiperProcess:
    """Launch a local command with piped input and no console on Windows.

    Discard process output: failures are logged using controlled errors and exit codes,
    not unbounded diagnostics that can contain local paths or supplied speech text.
    """
    return _LocalPiperProcess(
        subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    )


class _LocalPiperProcess:
    """Adapt Popen to explicitly close stdin after timeout/cancellation."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process

    def communicate(
        self, input: bytes | None = None, timeout: float | None = None
    ) -> tuple[bytes | None, bytes | None]:
        return self._process.communicate(input=input, timeout=timeout)

    def poll(self) -> int | None:
        return self._process.poll()

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    def wait(self, timeout: float | None = None) -> int:
        return self._process.wait(timeout=timeout)

    def close(self) -> None:
        if self._process.stdin is not None:
            self._process.stdin.close()
