"""Typed game-domain data such as statuses, results, and player configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PlayerColor(str, Enum):
    """A chess colour controlled by either the player or the engine."""

    WHITE = "white"
    BLACK = "black"

    @property
    def opponent(self) -> PlayerColor:
        """Return the other chess colour."""
        if self is PlayerColor.WHITE:
            return PlayerColor.BLACK
        return PlayerColor.WHITE


class GameStatus(str, Enum):
    """The user-visible status of a game."""

    ACTIVE = "active"
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    DRAW = "draw"
    RESIGNED = "resigned"


class GameResult(str, Enum):
    """The standard result notation shared by PGN and chess score sheets."""

    WHITE_WIN = "1-0"
    BLACK_WIN = "0-1"
    DRAW = "1/2-1/2"


@dataclass(frozen=True, slots=True)
class GameOutcome:
    """A terminal status, result, and user-facing explanation."""

    status: GameStatus
    result: GameResult
    message: str
