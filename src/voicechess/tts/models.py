"""Immutable announcement data for the text-to-speech boundary."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class AnnouncementStatus(StrEnum):
    """Availability of one engine-move announcement."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class Announcement:
    """A safe snapshot of an announcement without process or file details."""

    announcement_id: UUID
    game_id: str
    text: str
    status: AnnouncementStatus
