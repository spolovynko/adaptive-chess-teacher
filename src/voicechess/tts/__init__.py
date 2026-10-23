"""Local text-to-speech service boundary."""

from voicechess.tts.errors import (
    TtsAnnouncementError,
    TtsError,
    TtsOutputValidationError,
    TtsShutdownError,
    TtsStartupError,
    TtsStartupTimeoutError,
    TtsSynthesisError,
    TtsTimeoutError,
    TtsUnavailableError,
)
from voicechess.tts.formatter import format_engine_move
from voicechess.tts.models import Announcement, AnnouncementStatus
from voicechess.tts.protocol import TtsService
from voicechess.tts.service import PiperSynthesizer

__all__ = [
    "Announcement",
    "AnnouncementStatus",
    "PiperSynthesizer",
    "TtsAnnouncementError",
    "TtsError",
    "TtsOutputValidationError",
    "TtsService",
    "TtsShutdownError",
    "TtsStartupError",
    "TtsStartupTimeoutError",
    "TtsSynthesisError",
    "TtsTimeoutError",
    "TtsUnavailableError",
    "format_engine_move",
]
