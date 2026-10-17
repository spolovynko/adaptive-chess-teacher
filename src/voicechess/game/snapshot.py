"""Read-only game data prepared for later API and browser consumers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from voicechess.game.models import GameResult, GameStatus, PlayerColor
from voicechess.state import GameState


@dataclass(frozen=True, slots=True, kw_only=True)
class GameSnapshot:
    """An immutable representation of one game's user-visible state."""

    game_id: str
    fen: str
    side_to_move: PlayerColor
    board: Mapping[str, str]
    moves: Sequence[str]
    status: GameStatus
    result: GameResult | None
    last_move: str | None
    message: str
    state: GameState

    def __post_init__(self) -> None:
        """Copy mutable inputs so a snapshot cannot expose internal game data."""
        object.__setattr__(self, "board", MappingProxyType(dict(self.board)))
        object.__setattr__(self, "moves", tuple(self.moves))
