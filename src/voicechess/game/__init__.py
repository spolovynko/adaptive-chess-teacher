"""Chess game domain package.

The package separates orchestration, domain data, snapshots, and game-specific errors
so the chess rules layer remains independent from the engine, API, and browser layers.
"""

from voicechess.game.controller import GameController
from voicechess.game.errors import (
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
from voicechess.game.models import GameOutcome, GameResult, GameStatus, PlayerColor
from voicechess.game.snapshot import GameSnapshot

__all__ = [
    "EngineMoveNotExpectedError",
    "EmptySanError",
    "GameError",
    "GameController",
    "GameOutcome",
    "GameNotActiveError",
    "GameResult",
    "GameStatus",
    "GameSnapshot",
    "IllegalEngineMoveError",
    "IllegalSanMoveError",
    "InvalidSanError",
    "MoveInputError",
    "PlayerColor",
    "PlayerMoveNotExpectedError",
]
