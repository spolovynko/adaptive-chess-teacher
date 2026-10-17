"""Tests for controlled game-domain errors."""

import pytest

from voicechess.game import (
    EmptySanError,
    EngineMoveNotExpectedError,
    GameError,
    GameNotActiveError,
    IllegalEngineMoveError,
    IllegalSanMoveError,
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
        (IllegalEngineMoveError(), "engine returned an illegal move"),
        (PlayerMoveNotExpectedError(), "player move is not expected"),
        (EngineMoveNotExpectedError(), "engine move is not expected"),
    ],
)
def test_game_errors_have_user_safe_messages(error: GameError, message: str) -> None:
    assert message in str(error)


def test_player_move_errors_share_a_common_base_class() -> None:
    for error in (EmptySanError(), InvalidSanError("invalid"), IllegalSanMoveError("Qh5")):
        assert isinstance(error, MoveInputError)
        assert isinstance(error, GameError)
