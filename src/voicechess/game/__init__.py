"""Chess game domain package.

The package separates orchestration, domain data, snapshots, and game-specific errors
so the chess rules layer remains independent from the engine, API, and browser layers.
"""

from voicechess.game.errors import (
    EmptySanError,
    GameError,
    GameNotActiveError,
    IllegalEngineMoveError,
    IllegalSanMoveError,
    InvalidSanError,
    MoveInputError,
)
from voicechess.game.models import GameResult, GameStatus, PlayerColor
from voicechess.game.snapshot import GameSnapshot

__all__ = [
    "EmptySanError",
    "GameError",
    "GameNotActiveError",
    "GameResult",
    "GameStatus",
    "GameSnapshot",
    "IllegalEngineMoveError",
    "IllegalSanMoveError",
    "InvalidSanError",
    "MoveInputError",
    "PlayerColor",
]
