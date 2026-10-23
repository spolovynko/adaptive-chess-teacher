"""Bounded in-memory ownership of the current game's latest announcement."""

from __future__ import annotations

import logging
from dataclasses import replace
from threading import RLock
from uuid import UUID, uuid4

from voicechess.config import Settings
from voicechess.logging import log_event
from voicechess.tts.audio import validate_wav_bytes
from voicechess.tts.errors import (
    TtsAnnouncementError,
    TtsOutputValidationError,
    TtsUnavailableError,
)
from voicechess.tts.models import MAX_ANNOUNCEMENT_TEXT_CHARS, Announcement, AnnouncementStatus


class AnnouncementStore:
    """Keep at most one announcement and one validated WAV; never persist replay audio."""

    def __init__(self, *, settings: Settings, logger: logging.Logger) -> None:
        self._sample_rate = settings.piper_expected_sample_rate_hz
        self._channels = settings.piper_output_channels
        self._logger = logger
        self._lock = RLock()
        self._game_id: str | None = None
        self._current: Announcement | None = None
        self._audio: bytes | None = None

    def activate_game(self, game_id: str) -> None:
        """Select the authoritative game; repeat activation preserves its announcement."""
        with self._lock:
            if self._game_id != game_id:
                self._clear("game_replaced")
                self._game_id = game_id

    def begin(self, *, game_id: str, text: str) -> Announcement:
        """Register one pending announcement, immediately superseding its predecessor."""
        if (
            not text.strip()
            or len(text) > MAX_ANNOUNCEMENT_TEXT_CHARS
            or any(char in text for char in "\r\n\0")
        ):
            raise TtsAnnouncementError
        with self._lock:
            if game_id != self._game_id:
                raise TtsUnavailableError
            self._clear("superseded")
            self._current = Announcement(
                announcement_id=uuid4(),
                game_id=game_id,
                text=text,
                status=AnnouncementStatus.PENDING,
            )
            log_event(
                self._logger,
                logging.INFO,
                "announcement_pending",
                game_id=game_id,
                metadata={"announcement_id": str(self._current.announcement_id)},
            )
            return self._current

    def complete(self, *, game_id: str, announcement_id: UUID, audio: bytes) -> bool:
        """Accept validated audio only for the current pending announcement.

        False means an expected stale/duplicate result was discarded. Failed output
        validation marks the current announcement failed and raises a controlled error.
        """
        with self._lock:
            current = self._pending(game_id, announcement_id)
            if current is None:
                return False
            try:
                validate_wav_bytes(audio, sample_rate=self._sample_rate, channels=self._channels)
            except TtsOutputValidationError:
                self.fail(game_id=game_id, announcement_id=announcement_id)
                raise
            self._audio = audio
            self._current = replace(current, status=AnnouncementStatus.READY)
            log_event(
                self._logger,
                logging.INFO,
                "announcement_audio_available",
                game_id=game_id,
                metadata={"announcement_id": str(announcement_id), "audio_bytes": len(audio)},
            )
            return True

    def fail(self, *, game_id: str, announcement_id: UUID) -> bool:
        """Mark only the matching pending announcement failed; never alter newer work."""
        with self._lock:
            current = self._pending(game_id, announcement_id)
            if current is None:
                return False
            self._audio = None
            self._current = replace(current, status=AnnouncementStatus.FAILED)
            log_event(
                self._logger,
                logging.WARNING,
                "announcement_failed",
                game_id=game_id,
                metadata={"announcement_id": str(announcement_id)},
            )
            return True

    def get(self, *, game_id: str, announcement_id: UUID) -> Announcement:
        """Return a safe immutable snapshot, rejecting other games or old IDs."""
        with self._lock:
            current = self._current
            if (
                game_id != self._game_id
                or current is None
                or current.announcement_id != announcement_id
            ):
                raise TtsUnavailableError
            return current

    def get_audio(self, *, game_id: str, announcement_id: UUID) -> bytes:
        """Return the latest ready WAV; pending, failed, and stale audio are unavailable."""
        with self._lock:
            current = self.get(game_id=game_id, announcement_id=announcement_id)
            if current.status is not AnnouncementStatus.READY or self._audio is None:
                raise TtsUnavailableError
            return self._audio

    def invalidate_game(self, game_id: str) -> None:
        """Forget a replaced game; invalidating an older game leaves a newer one alone."""
        with self._lock:
            if game_id == self._game_id:
                self._clear("game_invalidated")
                self._game_id = None

    def clear(self) -> None:
        """Release replay memory and invalidate pending results during shutdown."""
        with self._lock:
            self._clear("shutdown")
            self._game_id = None

    def _pending(self, game_id: str, announcement_id: UUID) -> Announcement | None:
        current = self._current
        if (
            game_id == self._game_id
            and current is not None
            and current.announcement_id == announcement_id
            and current.status is AnnouncementStatus.PENDING
        ):
            return current
        log_event(
            self._logger,
            logging.INFO,
            "announcement_result_discarded",
            game_id=game_id,
            metadata={"announcement_id": str(announcement_id)},
        )
        return None

    def _clear(self, reason: str) -> None:
        current = self._current
        self._current = None
        self._audio = None
        if current is not None:
            log_event(
                self._logger,
                logging.INFO,
                "announcement_cleared",
                game_id=current.game_id,
                metadata={"announcement_id": str(current.announcement_id), "reason": reason},
            )
