"""Tests for controlled game-domain errors."""

import pytest

from voicechess.game import (
    EmptySanError,
    EngineMoveNotExpectedError,
    GameError,
    GameNotActiveError,
    IllegalBoardMoveError,
    IllegalEngineMoveError,
    IllegalSanMoveError,
    InvalidBoardMoveError,
    InvalidSanError,
    MoveInputError,
    PlayerMoveNotExpectedError,
)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (GameNotActiveError(), "no longer active"),
        (EmptySanError(), "Enter a move"),
        (InvalidSanError("horse to e4"), "not valid"),
        (IllegalSanMoveError("Qh5"), "not a legal move"),
        (InvalidBoardMoveError("z9", "e4"), "board move"),
        (IllegalBoardMoveError("e2", "e5"), "cannot legally move"),
        (IllegalEngineMoveError(), "engine returned an illegal move"),
        (PlayerMoveNotExpectedError(), "player move is not expected"),
        (EngineMoveNotExpectedError(), "engine move is not expected"),
    ],
)
def test_game_errors_have_user_safe_messages(error: GameError, message: str) -> None:
    assert message in str(error)


def test_player_move_errors_share_a_common_base_class() -> None:
    for error in (
        EmptySanError(),
        InvalidSanError("invalid"),
        IllegalSanMoveError("Qh5"),
        InvalidBoardMoveError("z9", "e4"),
        IllegalBoardMoveError("e2", "e5"),
    ):
        assert isinstance(error, MoveInputError)
        assert isinstance(error, GameError)
