"""Tests for structured application logging."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from voicechess.config import Settings
from voicechess.logging import (
    configure_logging,
    log_event,
    log_state_transition,
    reset_logging,
    timed_event,
)


@pytest.fixture
def logger_and_destination(tmp_path: Path) -> Iterator[tuple[logging.Logger, Path]]:
    destination = tmp_path / "voicechess.jsonl"
    logger = configure_logging(Settings(log_destination=destination))
    yield logger, destination
    reset_logging(logger)


def read_events(destination: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]


def test_log_event_writes_structured_metadata(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination

    log_event(
        logger,
        logging.INFO,
        "player_move_applied",
        game_id="game-123",
        duration_ms=12.3456,
        metadata={"san": "e4"},
    )

    event = read_events(destination)[0]
    assert event["event"] == "player_move_applied"
    assert event["level"] == "INFO"
    assert event["logger"] == "voicechess"
    assert event["game_id"] == "game-123"
    assert event["duration_ms"] == 12.346
    assert event["metadata"] == {"san": "e4"}
    assert event["timestamp"].endswith("Z")
    assert datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00")).tzinfo


def test_state_transition_has_game_and_state_context(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination

    log_state_transition(
        logger,
        game_id="game-123",
        state_from="PLAYER_INPUT",
        state_to="RESOLVING",
    )

    event = read_events(destination)[0]
    assert event["event"] == "state_transition"
    assert event["state_from"] == "PLAYER_INPUT"
    assert event["state_to"] == "RESOLVING"


def test_timed_event_records_duration_on_success(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination

    with timed_event(logger, "snapshot_built", game_id="game-123"):
        pass

    event = read_events(destination)[0]
    assert event["event"] == "snapshot_built"
    assert event["level"] == "INFO"
    assert isinstance(event["duration_ms"], float)
    assert event["duration_ms"] >= 0


def test_timed_event_records_safe_error_details(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination

    with pytest.raises(RuntimeError, match="engine unavailable"):
        with timed_event(logger, "engine_move_requested", game_id="game-123"):
            raise RuntimeError("engine unavailable")

    event = read_events(destination)[0]
    assert event["level"] == "ERROR"
    assert event["error"] == {"type": "RuntimeError", "message": "engine unavailable"}


def test_log_level_filters_lower_severity_events(tmp_path: Path) -> None:
    destination = tmp_path / "voicechess.jsonl"
    logger = configure_logging(Settings(log_destination=destination, log_level="ERROR"))

    log_event(logger, logging.INFO, "ignored_event")
    log_event(logger, logging.ERROR, "recorded_event")
    reset_logging(logger)

    assert [event["event"] for event in read_events(destination)] == ["recorded_event"]
