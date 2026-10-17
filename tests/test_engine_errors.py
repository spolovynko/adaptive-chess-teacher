"""Tests for controlled Stockfish boundary errors."""

import pytest

from voicechess.engine import (
    InvalidEnginePositionError,
    StockfishIllegalMoveError,
    StockfishMoveError,
    StockfishMoveTimeoutError,
    StockfishNoMoveError,
    StockfishNotRunningError,
    StockfishShutdownError,
    StockfishStartupError,
    StockfishStartupTimeoutError,
)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (StockfishNotRunningError(), "Stockfish is not running."),
        (
            StockfishStartupError("stockfish-test"),
            "Unable to start Stockfish at 'stockfish-test'.",
        ),
        (
            StockfishStartupTimeoutError("stockfish-test", 500),
            "Stockfish did not start within 500 ms.",
        ),
        (InvalidEnginePositionError(), "Stockfish received an invalid chess position."),
        (StockfishNoMoveError(), "Stockfish did not return a move for this position."),
        (
            StockfishIllegalMoveError("e7e4"),
            "Stockfish returned an illegal move: e7e4.",
        ),
        (StockfishMoveError(), "Stockfish failed while calculating a move."),
        (
            StockfishMoveTimeoutError(750),
            "Stockfish did not return a move within 750 ms.",
        ),
        (StockfishShutdownError(), "Stockfish could not be shut down cleanly."),
    ],
)
def test_engine_errors_have_stable_messages(error: Exception, message: str) -> None:
    assert str(error) == message
