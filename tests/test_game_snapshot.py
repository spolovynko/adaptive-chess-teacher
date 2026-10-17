"""Tests for immutable game snapshots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError

import pytest

from voicechess.game import GameSnapshot, GameStatus, PlayerColor
from voicechess.state import GameState


def make_snapshot(board: Mapping[str, str], moves: Sequence[str]) -> GameSnapshot:
    return GameSnapshot(
        game_id="game-123",
        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        side_to_move=PlayerColor.WHITE,
        board=board,
        moves=moves,
        status=GameStatus.ACTIVE,
        result=None,
        last_move=None,
        message="White to move.",
        state=GameState.PLAYER_INPUT,
    )


def test_snapshot_exposes_expected_game_data() -> None:
    snapshot = make_snapshot({"a1": "R", "e1": "K"}, ("e4", "e5"))

    assert snapshot.game_id == "game-123"
    assert snapshot.side_to_move is PlayerColor.WHITE
    assert snapshot.board == {"a1": "R", "e1": "K"}
    assert snapshot.moves == ("e4", "e5")
    assert snapshot.state is GameState.PLAYER_INPUT


def test_snapshot_copies_and_locks_board_and_move_data() -> None:
    board = {"a1": "R"}
    moves = ["e4"]
    snapshot = make_snapshot(board, moves)

    board["e1"] = "K"
    moves.append("e5")

    assert snapshot.board == {"a1": "R"}
    assert snapshot.moves == ("e4",)
    with pytest.raises(TypeError):
        snapshot.board["e1"] = "K"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        snapshot.message = "Changed."  # type: ignore[misc]
