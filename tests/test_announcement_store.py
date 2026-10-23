"""Announcement identity and bounded replay retention, without Piper."""

import io
import logging
import wave
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from voicechess.config import Settings
from voicechess.tts import (
    AnnouncementStatus,
    AnnouncementStore,
    TtsAnnouncementError,
    TtsOutputValidationError,
    TtsUnavailableError,
)


def wav_audio(value: int = 1, *, rate: int = 22_050) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(value.to_bytes(2, "little") * 32)
    return buffer.getvalue()


@pytest.fixture
def store() -> AnnouncementStore:
    return AnnouncementStore(
        settings=Settings(_env_file=None, piper_expected_sample_rate_hz=22_050),
        logger=logging.getLogger("tts-test"),
    )


def test_latest_announcement_can_be_read_and_replayed(store: AnnouncementStore) -> None:
    store.activate_game("game-a")
    pending = store.begin(game_id="game-a", text="Black plays knight f6.")
    assert pending.status is AnnouncementStatus.PENDING
    with pytest.raises(TtsUnavailableError):
        store.get_audio(game_id="game-a", announcement_id=pending.announcement_id)
    assert store.complete(
        game_id="game-a", announcement_id=pending.announcement_id, audio=wav_audio()
    )
    ready = store.get(game_id="game-a", announcement_id=pending.announcement_id)
    assert ready.status is AnnouncementStatus.READY
    assert pending.status is AnnouncementStatus.PENDING
    assert store.get_audio(game_id="game-a", announcement_id=pending.announcement_id) == wav_audio()
    assert not hasattr(ready, "path")


def test_new_announcement_replaces_old_replay(store: AnnouncementStore) -> None:
    store.activate_game("game-a")
    old = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    store.complete(game_id="game-a", announcement_id=old.announcement_id, audio=wav_audio())
    current = store.begin(game_id="game-a", text="Black plays knight f6.")
    assert current.announcement_id != old.announcement_id
    with pytest.raises(TtsUnavailableError):
        store.get_audio(game_id="game-a", announcement_id=old.announcement_id)
    assert not store.complete(
        game_id="game-a", announcement_id=old.announcement_id, audio=wav_audio()
    )


def test_late_result_from_previous_game_cannot_replace_current_audio(
    store: AnnouncementStore,
) -> None:
    store.activate_game("game-a")
    old = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    store.activate_game("game-b")
    current = store.begin(game_id="game-b", text="Black plays pawn to c5.")
    store.complete(game_id="game-b", announcement_id=current.announcement_id, audio=wav_audio(2))
    assert not store.complete(
        game_id="game-a", announcement_id=old.announcement_id, audio=wav_audio()
    )
    assert not store.fail(game_id="game-a", announcement_id=old.announcement_id)
    store.invalidate_game("game-a")
    assert store.get_audio(game_id="game-b", announcement_id=current.announcement_id) == wav_audio(
        2
    )


def test_game_invalidation_and_shutdown_drop_replay(store: AnnouncementStore) -> None:
    store.activate_game("game-a")
    old = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    store.invalidate_game("game-a")
    with pytest.raises(TtsUnavailableError):
        store.get(game_id="game-a", announcement_id=old.announcement_id)
    store.activate_game("game-b")
    current = store.begin(game_id="game-b", text="Black plays knight f6.")
    store.clear()
    assert not store.complete(
        game_id="game-b", announcement_id=current.announcement_id, audio=wav_audio()
    )


def test_inactive_game_cannot_register_an_announcement(store: AnnouncementStore) -> None:
    with pytest.raises(TtsUnavailableError):
        store.begin(game_id="game-a", text="Black plays pawn to e5.")


def test_duplicate_and_wrong_identity_results_do_not_change_ready_audio(
    store: AnnouncementStore,
) -> None:
    store.activate_game("game-a")
    current = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    assert not store.complete(
        game_id="game-b", announcement_id=current.announcement_id, audio=wav_audio()
    )
    assert not store.complete(game_id="game-a", announcement_id=uuid4(), audio=wav_audio())
    assert store.complete(
        game_id="game-a", announcement_id=current.announcement_id, audio=wav_audio()
    )
    assert not store.complete(
        game_id="game-a", announcement_id=current.announcement_id, audio=wav_audio(2)
    )
    assert not store.fail(game_id="game-a", announcement_id=current.announcement_id)
    store.activate_game("game-a")
    assert store.get_audio(game_id="game-a", announcement_id=current.announcement_id) == wav_audio()


@pytest.mark.parametrize("audio", [b"", b"invalid", wav_audio()[:-1], wav_audio(rate=16_000)])
def test_bad_output_marks_only_current_announcement_failed(
    store: AnnouncementStore, audio: bytes
) -> None:
    store.activate_game("game-a")
    current = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    with pytest.raises(TtsOutputValidationError):
        store.complete(game_id="game-a", announcement_id=current.announcement_id, audio=audio)
    assert (
        store.get(game_id="game-a", announcement_id=current.announcement_id).status
        is AnnouncementStatus.FAILED
    )
    with pytest.raises(TtsUnavailableError):
        store.get_audio(game_id="game-a", announcement_id=current.announcement_id)


def test_oversized_audio_is_not_retained(
    store: AnnouncementStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.activate_game("game-a")
    current = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    monkeypatch.setattr("voicechess.tts.audio.MAX_AUDIO_BYTES", 32)
    with pytest.raises(TtsOutputValidationError):
        store.complete(game_id="game-a", announcement_id=current.announcement_id, audio=wav_audio())


@pytest.mark.parametrize("text", ["", " ", "move\n", "move\r", "move\0", "a" * 4097])
def test_invalid_text_does_not_replace_existing_announcement(
    store: AnnouncementStore, text: str
) -> None:
    store.activate_game("game-a")
    current = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    with pytest.raises(TtsAnnouncementError):
        store.begin(game_id="game-a", text=text)
    assert store.get(game_id="game-a", announcement_id=current.announcement_id) == current


def test_late_thread_result_is_rejected_after_game_reset(store: AnnouncementStore) -> None:
    store.activate_game("game-a")
    old = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    entered, released = Event(), Event()

    def late_result() -> bool:
        entered.set()
        assert released.wait(timeout=2)
        return store.complete(
            game_id="game-a", announcement_id=old.announcement_id, audio=wav_audio()
        )

    with ThreadPoolExecutor(max_workers=1) as worker:
        task = worker.submit(late_result)
        assert entered.wait(timeout=2)
        try:
            store.activate_game("game-b")
            current = store.begin(game_id="game-b", text="Black plays pawn to c5.")
            store.complete(
                game_id="game-b", announcement_id=current.announcement_id, audio=wav_audio(2)
            )
        finally:
            released.set()
        assert not task.result(timeout=2)
    assert store.get_audio(game_id="game-b", announcement_id=current.announcement_id) == wav_audio(
        2
    )


def test_failed_synthesis_releases_replay_and_allows_next_move(store: AnnouncementStore) -> None:
    store.activate_game("game-a")
    current = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    assert store.fail(game_id="game-a", announcement_id=current.announcement_id)
    assert not store.complete(
        game_id="game-a", announcement_id=current.announcement_id, audio=wav_audio()
    )
    next_move = store.begin(game_id="game-a", text="Black plays knight f6.")
    assert store.complete(
        game_id="game-a", announcement_id=next_move.announcement_id, audio=wav_audio(2)
    )


def test_retention_and_discard_events_include_identity(
    store: AnnouncementStore, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="tts-test")
    store.activate_game("game-a")
    current = store.begin(game_id="game-a", text="Black plays pawn to e5.")
    store.complete(game_id="game-a", announcement_id=current.announcement_id, audio=wav_audio())
    store.clear()
    store.complete(game_id="game-a", announcement_id=current.announcement_id, audio=wav_audio())
    events = {record.event: record for record in caplog.records}
    assert events["announcement_audio_available"].metadata["announcement_id"] == str(
        current.announcement_id
    )
    assert events["announcement_cleared"].metadata["reason"] == "shutdown"
    assert events["announcement_result_discarded"].game_id == "game-a"
