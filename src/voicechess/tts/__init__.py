"""Local text-to-speech service boundary."""

from voicechess.tts.errors import (
    TtsAnnouncementError,
    TtsError,
    TtsOutputValidationError,
    TtsShutdownError,
    TtsStartupError,
    TtsSynthesisError,
    TtsTimeoutError,
    TtsUnavailableError,
)
from voicechess.tts.formatter import format_engine_move
from voicechess.tts.models import Announcement, AnnouncementStatus
from voicechess.tts.protocol import TtsService

__all__ = [
    "Announcement",
    "AnnouncementStatus",
    "TtsAnnouncementError",
    "TtsError",
    "TtsOutputValidationError",
    "TtsService",
    "TtsShutdownError",
    "TtsStartupError",
    "TtsSynthesisError",
    "TtsTimeoutError",
    "TtsUnavailableError",
    "format_engine_move",
]
