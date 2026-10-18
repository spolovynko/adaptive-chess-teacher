"""Validated JSON contracts for the future FastAPI boundary."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from voicechess.game import GameResult, GameSnapshot, GameStatus, PlayerColor
from voicechess.pgn import PgnExportResult
from voicechess.state import GameState

SquareName = Annotated[str, StringConstraints(pattern=r"^[a-h][1-8]$")]
PieceSymbol = Literal["P", "N", "B", "R", "Q", "K", "p", "n", "b", "r", "q", "k"]


class ApiModel(BaseModel):
    """Base API model that rejects fields outside its declared contract."""

    model_config = ConfigDict(extra="forbid")


class MoveRequest(ApiModel):
    """One player move written in Standard Algebraic Notation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    san: str = Field(min_length=1, max_length=32)


class BoardMoveRequest(ApiModel):
    """One player move selected by source and destination board squares."""

    from_square: SquareName
    to_square: SquareName
    promotion: Literal["q", "r", "b", "n"] | None = None


class GameSnapshotResponse(ApiModel):
    """Complete browser-facing representation of the current game."""

    game_id: UUID
    fen: str = Field(min_length=1)
    side_to_move: PlayerColor
    board: dict[SquareName, PieceSymbol]
    moves: list[str]
    status: GameStatus
    result: GameResult | None
    last_move: str | None
    message: str
    state: GameState

    @classmethod
    def from_snapshot(cls, snapshot: GameSnapshot) -> Self:
        """Copy an immutable domain snapshot into the validated API contract."""
        return cls.model_validate(
            {
                "game_id": snapshot.game_id,
                "fen": snapshot.fen,
                "side_to_move": snapshot.side_to_move,
                "board": dict(snapshot.board),
                "moves": list(snapshot.moves),
                "status": snapshot.status,
                "result": snapshot.result,
                "last_move": snapshot.last_move,
                "message": snapshot.message,
                "state": snapshot.state,
            }
        )


class HealthResponse(ApiModel):
    """Readiness of the local application and Stockfish process."""

    status: Literal["ok", "degraded"]
    stockfish_ready: bool


class ErrorDetail(ApiModel):
    """Stable machine-readable code and safe user-facing explanation."""

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1)


class ErrorResponse(ApiModel):
    """Consistent envelope for controlled API failures."""

    error: ErrorDetail

    @classmethod
    def from_error(cls, code: str, error: BaseException) -> Self:
        """Create a safe response from a controlled application exception."""
        return cls(error=ErrorDetail(code=code, message=str(error)))


class PgnExportResponse(ApiModel):
    """Download-ready PGN content without exposing a server filesystem path."""

    game_id: UUID
    filename: str = Field(pattern=r"^[A-Za-z0-9_.-]+\.pgn$")
    pgn: str = Field(min_length=1)

    @classmethod
    def from_result(cls, result: PgnExportResult) -> Self:
        """Convert an internal export result into its public representation."""
        return cls.model_validate(
            {
                "game_id": result.game_id,
                "filename": result.filename,
                "pgn": result.pgn,
            }
        )


__all__ = [
    "BoardMoveRequest",
    "ErrorDetail",
    "ErrorResponse",
    "GameSnapshotResponse",
    "HealthResponse",
    "MoveRequest",
    "PgnExportResponse",
    "PieceSymbol",
    "SquareName",
]
