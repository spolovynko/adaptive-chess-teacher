"""Tests for construction of the core game controller."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import chess
import pytest

from voicechess.config import Settings
from voicechess.game import (
    EmptySanError,
    EngineMoveNotExpectedError,
    GameController,
    GameNotActiveError,
    GameResult,
    GameStatus,
    IllegalEngineMoveError,
    IllegalSanMoveError,
    InvalidSanError,
    PlayerColor,
    PlayerMoveNotExpectedError,
)
from voicechess.logging import configure_logging, reset_logging
from voicechess.state import GameState

TEST_GAME_ID = UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def logger_and_destination(tmp_path: Path) -> Iterator[tuple[logging.Logger, Path]]:
    destination = tmp_path / "voicechess.jsonl"
    logger = configure_logging(Settings(log_destination=destination))
    yield logger, destination
    reset_logging(logger)


def read_events(destination: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]


def test_new_game_has_standard_initial_state(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination

    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)

    assert game.game_id == str(TEST_GAME_ID)
    assert game.player_color is PlayerColor.WHITE
    assert game.fen == chess.STARTING_FEN
    assert game.side_to_move is PlayerColor.WHITE
    assert game.moves == ()
    assert game.status is GameStatus.ACTIVE
    assert game.result is None
    assert game.last_move is None
    assert game.message == "White to move."
    assert game.state is GameState.PLAYER_INPUT


def test_game_creation_logs_identity_and_initial_transition(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination

    GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)

    events = read_events(destination)
    assert [event["event"] for event in events] == ["game_created", "state_transition"]
    assert events[0]["game_id"] == str(TEST_GAME_ID)
    assert events[0]["metadata"] == {"player_color": "white"}
    assert events[1]["state_from"] == "IDLE"
    assert events[1]["state_to"] == "PLAYER_INPUT"


def test_default_game_ids_are_unique_and_valid_uuids(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination

    first = GameController(logger=logger)
    second = GameController(logger=logger)

    assert first.game_id != second.game_id
    assert str(UUID(first.game_id)) == first.game_id
    assert str(UUID(second.game_id)) == second.game_id


def test_move_history_property_does_not_expose_mutable_storage(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)

    assert isinstance(game.moves, tuple)


def test_valid_player_and_engine_moves_complete_a_turn(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)

    assert game.submit_player_san("  e4  ") == "e4"
    assert game.state is GameState.ENGINE_TURN
    assert game.message == "Black is thinking."

    assert game.apply_engine_move(chess.Move.from_uci("e7e5")) == "e5"
    assert game.moves == ("e4", "e5")
    assert game.last_move == "e5"
    assert game.side_to_move is PlayerColor.WHITE
    assert game.state is GameState.PLAYER_INPUT
    assert game.message == "White to move."


@pytest.mark.parametrize(
    ("san", "error_type"),
    [
        ("   ", EmptySanError),
        ("horse to e4", InvalidSanError),
        ("e5", IllegalSanMoveError),
    ],
)
def test_rejected_player_input_preserves_game_state(
    logger_and_destination: tuple[logging.Logger, Path],
    san: str,
    error_type: type[Exception],
) -> None:
    logger, destination = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)
    original_fen = game.fen

    with pytest.raises(error_type):
        game.submit_player_san(san)

    assert game.fen == original_fen
    assert game.moves == ()
    assert game.state is GameState.PLAYER_INPUT
    assert read_events(destination)[-1]["event"] == "player_move_rejected"


def test_player_move_is_rejected_while_engine_is_expected(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)
    game.submit_player_san("e4")

    with pytest.raises(PlayerMoveNotExpectedError):
        game.submit_player_san("Nf3")

    assert game.moves == ("e4",)
    assert game.state is GameState.ENGINE_TURN


def test_illegal_engine_move_preserves_position(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)
    game.submit_player_san("e4")
    original_fen = game.fen

    with pytest.raises(IllegalEngineMoveError, match="e7e4"):
        game.apply_engine_move(chess.Move.from_uci("e7e4"))

    assert game.fen == original_fen
    assert game.moves == ("e4",)
    assert game.state is GameState.ENGINE_TURN


def test_engine_move_is_rejected_when_player_input_is_expected(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)

    with pytest.raises(EngineMoveNotExpectedError):
        game.apply_engine_move(chess.Move.from_uci("e7e5"))


def test_player_checkmate_sets_terminal_status_and_result(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)
    game.submit_player_san("e4")
    game.apply_engine_move(chess.Move.from_uci("e7e5"))
    game.submit_player_san("Qh5")
    game.apply_engine_move(chess.Move.from_uci("b8c6"))
    game.submit_player_san("Bc4")
    game.apply_engine_move(chess.Move.from_uci("g8f6"))

    assert game.submit_player_san("Qxf7#") == "Qxf7#"
    assert game.status is GameStatus.CHECKMATE
    assert game.result is GameResult.WHITE_WIN
    assert game.message == "White wins by checkmate."
    assert game.state is GameState.GAME_OVER

    with pytest.raises(GameNotActiveError):
        game.submit_player_san("d4")


def test_engine_checkmate_sets_terminal_status_and_result(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)
    game.submit_player_san("f3")
    game.apply_engine_move(chess.Move.from_uci("e7e5"))
    game.submit_player_san("g4")

    assert game.apply_engine_move(chess.Move.from_uci("d8h4")) == "Qh4#"
    assert game.status is GameStatus.CHECKMATE
    assert game.result is GameResult.BLACK_WIN
    assert game.message == "Black wins by checkmate."
    assert game.state is GameState.GAME_OVER


def test_resignation_ends_game_and_cannot_repeat(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)

    game.resign()

    assert game.status is GameStatus.RESIGNED
    assert game.result is GameResult.BLACK_WIN
    assert game.message == "White resigned. Black wins."
    assert game.state is GameState.GAME_OVER
    with pytest.raises(GameNotActiveError):
        game.resign()


def test_new_game_replaces_identity_and_all_mutable_state(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    ids = iter(
        [
            TEST_GAME_ID,
            UUID("87654321-4321-8765-4321-876543218765"),
        ]
    )
    game = GameController(logger=logger, game_id_factory=lambda: next(ids))
    game.submit_player_san("e4")
    old_game_id = game.game_id

    snapshot = game.new_game()

    assert game.game_id != old_game_id
    assert snapshot.game_id == game.game_id
    assert game.fen == chess.STARTING_FEN
    assert game.moves == ()
    assert game.status is GameStatus.ACTIVE
    assert game.result is None
    assert game.last_move is None
    assert game.state is GameState.PLAYER_INPUT


def test_snapshot_is_complete_and_does_not_change_after_future_moves(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)
    initial = game.snapshot()

    game.submit_player_san("e4")

    assert len(initial.board) == 32
    assert initial.board["a1"] == "R"
    assert initial.board["a8"] == "r"
    assert initial.moves == ()
    assert initial.fen == chess.STARTING_FEN
    assert game.snapshot().moves == ("e4",)


def test_moves_and_snapshots_emit_duration_events(
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)

    game.submit_player_san("e4")
    game.apply_engine_move(chess.Move.from_uci("e7e5"))
    game.snapshot()

    timed_events = {
        event["event"]: event["duration_ms"]
        for event in read_events(destination)
        if "duration_ms" in event
    }
    assert "san_resolved" in timed_events
    assert "player_move_applied" in timed_events
    assert "engine_move_applied" in timed_events
    assert "snapshot_built" in timed_events
    assert all(duration >= 0 for duration in timed_events.values())
