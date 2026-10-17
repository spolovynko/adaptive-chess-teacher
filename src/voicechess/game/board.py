"""Read-only conversions from python-chess board state."""

from __future__ import annotations

import chess


def piece_map(board: chess.Board) -> dict[str, str]:
    """Return occupied algebraic squares mapped to standard piece symbols."""
    return {
        chess.square_name(square): piece.symbol()
        for square in chess.SQUARES
        if (piece := board.piece_at(square)) is not None
    }
