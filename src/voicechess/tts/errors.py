"""Controlled failures at the local text-to-speech boundary."""


class TtsError(RuntimeError):
    """Base exception for local text-to-speech failures."""


class TtsAnnouncementError(TtsError):
    """Raised when engine notation cannot be converted into an announcement."""

    def __init__(self) -> None:
        super().__init__("The engine move could not be converted into speech text.")


class TtsStartupError(TtsError):
    """Raised when the text-to-speech service cannot start."""

    def __init__(self) -> None:
        super().__init__("Local speech could not be started.")


class TtsSynthesisError(TtsError):
    """Raised when an announcement cannot be synthesized."""

    def __init__(self) -> None:
        super().__init__("The engine move could not be spoken.")


class TtsStartupTimeoutError(TtsStartupError):
    """Raised when the Piper startup probe exceeds its deadline."""

    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        TtsError.__init__(self, "Local speech startup timed out.")


class TtsTimeoutError(TtsSynthesisError):
    """Raised when speech synthesis exceeds its deadline."""

    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        TtsError.__init__(self, "Speech generation timed out.")


class TtsOutputValidationError(TtsSynthesisError):
    """Raised when generated audio is missing or invalid."""

    def __init__(self) -> None:
        TtsError.__init__(self, "Generated speech audio is invalid.")


class TtsUnavailableError(TtsError):
    """Raised when an announcement or its audio is unavailable."""

    def __init__(self) -> None:
        super().__init__("The engine move announcement is unavailable.")


class TtsShutdownError(TtsError):
    """Raised when the text-to-speech service cannot stop cleanly."""

    def __init__(self) -> None:
        super().__init__("Local speech could not be stopped cleanly.")


class TtsStorageError(TtsError):
    """Raised when private speech work files cannot be managed safely."""

    def __init__(self) -> None:
        super().__init__("Local speech audio could not be managed.")
