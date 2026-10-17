"""Tests for the game lifecycle state machine."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from voicechess.config import Settings
from voicechess.logging import configure_logging, reset_logging
from voicechess.state import GameState, GameStateMachine, InvalidStateTransition


@pytest.fixture
def machine_and_destination(tmp_path: Path) -> Iterator[tuple[GameStateMachine, Path]]:
    destination = tmp_path / "voicechess.jsonl"
    logger = configure_logging(Settings(log_destination=destination))
    machine = GameStateMachine(game_id="game-123", logger=logger)
    yield machine, destination
    reset_logging(logger)


def read_events(destination: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]


def test_machine_starts_idle(machine_and_destination: tuple[GameStateMachine, Path]) -> None:
    machine, _ = machine_and_destination

    assert machine.state is GameState.IDLE
    assert machine.can_transition_to(GameState.PLAYER_INPUT)
    assert not machine.can_transition_to(GameState.ENGINE_TURN)


def test_standard_move_cycle_is_valid_and_logged(
    machine_and_destination: tuple[GameStateMachine, Path],
) -> None:
    machine, destination = machine_and_destination

    machine.start()
    for state in (
        GameState.RESOLVING,
        GameState.APPLYING_PLAYER_MOVE,
        GameState.ENGINE_TURN,
        GameState.APPLYING_ENGINE_MOVE,
        GameState.RETURNING_SNAPSHOT,
        GameState.PLAYER_INPUT,
    ):
        machine.transition_to(state)

    events = read_events(destination)
    assert machine.state is GameState.PLAYER_INPUT
    assert len(events) == 7
    assert all(event["event"] == "state_transition" for event in events)
    assert events[0]["state_from"] == "IDLE"
    assert events[-1]["state_to"] == "PLAYER_INPUT"


def test_invalid_transition_preserves_state_and_logs_warning(
    machine_and_destination: tuple[GameStateMachine, Path],
) -> None:
    machine, destination = machine_and_destination

    with pytest.raises(InvalidStateTransition, match="IDLE to ENGINE_TURN"):
        machine.transition_to(GameState.ENGINE_TURN)

    event = read_events(destination)[0]
    assert machine.state is GameState.IDLE
    assert event["event"] == "state_transition_rejected"
    assert event["level"] == "WARNING"
    assert event["state_from"] == "IDLE"
    assert event["state_to"] == "ENGINE_TURN"


def test_game_over_is_reachable_from_an_active_stage(
    machine_and_destination: tuple[GameStateMachine, Path],
) -> None:
    machine, destination = machine_and_destination
    machine.start()
    machine.transition_to(GameState.RESOLVING)

    machine.mark_game_over()

    event = read_events(destination)[-1]
    assert machine.state is GameState.GAME_OVER
    assert event["state_from"] == "RESOLVING"
    assert event["state_to"] == "GAME_OVER"


def test_rejected_resolution_can_return_to_player_input(
    machine_and_destination: tuple[GameStateMachine, Path],
) -> None:
    machine, destination = machine_and_destination
    machine.start()
    machine.transition_to(GameState.RESOLVING)

    machine.transition_to(GameState.PLAYER_INPUT)

    events = read_events(destination)
    assert machine.state is GameState.PLAYER_INPUT
    assert events[-1]["state_from"] == "RESOLVING"
    assert events[-1]["state_to"] == "PLAYER_INPUT"


def test_engine_failure_can_return_to_player_input(
    machine_and_destination: tuple[GameStateMachine, Path],
) -> None:
    machine, destination = machine_and_destination
    machine.start()
    machine.transition_to(GameState.RESOLVING)
    machine.transition_to(GameState.APPLYING_PLAYER_MOVE)
    machine.transition_to(GameState.ENGINE_TURN)

    machine.transition_to(GameState.PLAYER_INPUT)

    assert machine.state is GameState.PLAYER_INPUT
    assert read_events(destination)[-1]["state_from"] == "ENGINE_TURN"
