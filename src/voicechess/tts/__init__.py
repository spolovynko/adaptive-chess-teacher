"""Local text-to-speech service boundary."""

from voicechess.tts.errors import (
    TtsError,
    TtsOutputValidationError,
    TtsShutdownError,
    TtsStartupError,
    TtsSynthesisError,
    TtsTimeoutError,
    TtsUnavailableError,
)
from voicechess.tts.models import Announcement, AnnouncementStatus
from voicechess.tts.protocol import TtsService

__all__ = [
    "Announcement",
    "AnnouncementStatus",
    "TtsError",
    "TtsOutputValidationError",
    "TtsService",
    "TtsShutdownError",
    "TtsStartupError",
    "TtsSynthesisError",
    "TtsTimeoutError",
    "TtsUnavailableError",
]
