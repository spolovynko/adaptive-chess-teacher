"""Tests for the local text-to-speech contract."""

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from voicechess.tts import (
    Announcement,
    AnnouncementStatus,
    TtsError,
    TtsOutputValidationError,
    TtsShutdownError,
    TtsStartupError,
    TtsSynthesisError,
    TtsTimeoutError,
    TtsUnavailableError,
)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (TtsStartupError(), "Local speech could not be started."),
        (TtsSynthesisError(), "The engine move could not be spoken."),
        (TtsTimeoutError(750), "Speech generation timed out."),
        (TtsOutputValidationError(), "Generated speech audio is invalid."),
        (TtsUnavailableError(), "The engine move announcement is unavailable."),
        (TtsShutdownError(), "Local speech could not be stopped cleanly."),
    ],
)
def test_tts_errors_have_safe_stable_messages(error: TtsError, message: str) -> None:
    assert str(error) == message
    assert isinstance(error, TtsError)


def test_synthesis_failures_share_a_common_type() -> None:
    assert isinstance(TtsTimeoutError(750), TtsSynthesisError)
    assert isinstance(TtsOutputValidationError(), TtsSynthesisError)
    assert TtsTimeoutError(750).timeout_ms == 750


def test_announcement_is_an_immutable_safe_snapshot() -> None:
    announcement = Announcement(
        announcement_id=uuid4(),
        game_id="game-123",
        text="Black plays knight f6.",
        status=AnnouncementStatus.PENDING,
    )

    assert announcement.status == "pending"
    assert not hasattr(announcement, "path")
    with pytest.raises(FrozenInstanceError):
        announcement.status = AnnouncementStatus.READY  # type: ignore[misc]


def test_announcement_status_values_are_stable() -> None:
    assert [status.value for status in AnnouncementStatus] == ["pending", "ready", "failed"]
