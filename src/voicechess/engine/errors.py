"""Controlled failures raised by the Stockfish service boundary."""

from __future__ import annotations


class StockfishError(RuntimeError):
    """Base exception for failures involving the local Stockfish process."""


class StockfishNotRunningError(StockfishError):
    """Raised when a move is requested before Stockfish has started."""

    def __init__(self) -> None:
        super().__init__("Stockfish is not running.")


class StockfishStartupError(StockfishError):
    """Raised when the configured Stockfish process cannot be initialized."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Unable to start Stockfish at '{path}'.")


class StockfishStartupTimeoutError(StockfishStartupError):
    """Raised when Stockfish does not initialize before its deadline."""

    def __init__(self, path: str, timeout_ms: int) -> None:
        self.path = path
        self.timeout_ms = timeout_ms
        StockfishError.__init__(self, f"Stockfish did not start within {timeout_ms} ms.")


class InvalidEnginePositionError(StockfishError):
    """Raised when the service receives an invalid FEN position."""

    def __init__(self) -> None:
        super().__init__("Stockfish received an invalid chess position.")


class StockfishNoMoveError(StockfishError):
    """Raised when a move is requested where none exists or none is returned."""

    def __init__(self) -> None:
        super().__init__("Stockfish did not return a move for this position.")


class StockfishIllegalMoveError(StockfishError):
    """Raised when Stockfish returns a move that is illegal in the supplied position."""

    def __init__(self, move: str) -> None:
        self.move = move
        super().__init__(f"Stockfish returned an illegal move: {move}.")


class StockfishMoveError(StockfishError):
    """Raised when Stockfish fails while calculating a move."""

    def __init__(self) -> None:
        super().__init__("Stockfish failed while calculating a move.")


class StockfishMoveTimeoutError(StockfishMoveError):
    """Raised when Stockfish exceeds the configured move deadline."""

    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        StockfishError.__init__(
            self,
            f"Stockfish did not return a move within {timeout_ms} ms.",
        )


class StockfishShutdownError(StockfishError):
    """Raised when Stockfish cannot be shut down cleanly."""

    def __init__(self) -> None:
        super().__init__("Stockfish could not be shut down cleanly.")
