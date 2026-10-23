"""Immutable announcement data for the text-to-speech boundary."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

# Engine announcements are short; bound input before requesting synthesis or retention.
MAX_ANNOUNCEMENT_TEXT_CHARS = 4_096


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
