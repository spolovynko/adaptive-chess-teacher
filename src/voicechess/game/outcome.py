"""Translate python-chess terminal outcomes into game-domain values."""

from __future__ import annotations

import chess

from voicechess.game.models import GameOutcome, GameResult, GameStatus

DRAW_MESSAGES: dict[chess.Termination, str] = {
    chess.Termination.STALEMATE: "Draw by stalemate.",
    chess.Termination.INSUFFICIENT_MATERIAL: "Draw by insufficient material.",
    chess.Termination.SEVENTYFIVE_MOVES: "Draw by the seventy-five-move rule.",
    chess.Termination.FIVEFOLD_REPETITION: "Draw by fivefold repetition.",
}


def automatic_outcome(board: chess.Board) -> GameOutcome | None:
    """Return an automatic result without claiming optional player draws."""
    outcome = board.outcome(claim_draw=False)
    if outcome is None:
        return None

    result = GameResult(outcome.result())
    if outcome.termination is chess.Termination.CHECKMATE:
        winner = "White" if outcome.winner == chess.WHITE else "Black"
        return GameOutcome(
            status=GameStatus.CHECKMATE,
            result=result,
            message=f"{winner} wins by checkmate.",
        )

    if outcome.termination is chess.Termination.STALEMATE:
        status = GameStatus.STALEMATE
    else:
        status = GameStatus.DRAW

    return GameOutcome(
        status=status,
        result=result,
        message=DRAW_MESSAGES.get(outcome.termination, "Game drawn."),
    )
