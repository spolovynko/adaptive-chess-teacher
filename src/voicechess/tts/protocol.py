"""Service contract for local engine-move announcements."""

from typing import Protocol
from uuid import UUID

from voicechess.tts.models import Announcement


class TtsService(Protocol):
    """Operations needed to manage speech independently of chess turns."""

    def start(self) -> None:
        """Prepare the local service for use."""

    def submit(self, *, game_id: str, text: str) -> Announcement:
        """Queue an announcement and return its current snapshot."""

    def get(self, *, game_id: str, announcement_id: UUID) -> Announcement:
        """Return the current snapshot for an announcement in a game."""

    def get_audio(self, *, game_id: str, announcement_id: UUID) -> bytes:
        """Return ready audio without exposing its local storage path."""

    def invalidate_game(self, game_id: str) -> None:
        """Invalidate announcements belonging to a replaced game."""

    def stop(self) -> None:
        """Stop the service and release its resources."""
