"""Synchronous lifecycle and move-selection boundary for local Stockfish."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import RLock
from time import perf_counter
from typing import Protocol

import chess
import chess.engine

from voicechess.config import Settings
from voicechess.engine.errors import (
    InvalidEnginePositionError,
    StockfishError,
    StockfishIllegalMoveError,
    StockfishMoveError,
    StockfishMoveTimeoutError,
    StockfishNoMoveError,
    StockfishNotRunningError,
    StockfishShutdownError,
    StockfishStartupError,
    StockfishStartupTimeoutError,
)
from voicechess.logging import log_event


class UciEngine(Protocol):
    """The subset of ``SimpleEngine`` used by the application."""

    timeout: float | None

    def configure(self, options: chess.engine.ConfigMapping) -> None:
        """Apply engine options."""

    def play(self, board: chess.Board, limit: chess.engine.Limit) -> chess.engine.PlayResult:
        """Calculate one move."""

    def quit(self) -> None:
        """Request a graceful process shutdown."""

    def close(self) -> None:
        """Force the engine transport closed."""


EngineFactory = Callable[[str, float], UciEngine]


def open_uci_engine(path: str, timeout_seconds: float) -> UciEngine:
    """Start and initialize one UCI engine process."""
    return chess.engine.SimpleEngine.popen_uci(path, timeout=timeout_seconds)


class StockfishService:
    """Own one Stockfish process and provide bounded, validated move selection."""

    def __init__(
        self,
        *,
        settings: Settings,
        logger: logging.Logger,
        engine_factory: EngineFactory = open_uci_engine,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._engine_factory = engine_factory
        self._engine: UciEngine | None = None
        self._lock = RLock()

    @property
    def is_running(self) -> bool:
        """Return whether this service currently owns an initialized engine."""
        with self._lock:
            return self._engine is not None

    @property
    def limit(self) -> chess.engine.Limit:
        """Build the normal Stockfish search limit from validated settings."""
        move_time = self._settings.engine_move_time_ms
        return chess.engine.Limit(
            depth=self._settings.engine_search_depth,
            time=None if move_time is None else move_time / 1_000,
        )

    def start(self) -> None:
        """Start Stockfish and configure its playing strength; do nothing if running."""
        with self._lock:
            if self._engine is not None:
                return

            path = self._settings.stockfish_path
            timeout_seconds = self._settings.engine_startup_timeout_ms / 1_000
            started_at = perf_counter()
            log_event(
                self._logger,
                logging.INFO,
                "stockfish_starting",
                metadata={"path": path, "timeout_ms": self._settings.engine_startup_timeout_ms},
            )

            engine: UciEngine | None = None
            error: StockfishError
            try:
                engine = self._engine_factory(path, timeout_seconds)
                engine.configure({"Skill Level": self._settings.stockfish_skill_level})
                engine.timeout = self._settings.engine_move_timeout_ms / 1_000
            except TimeoutError as exc:
                if engine is not None:
                    self._close_without_raising(engine)
                error = StockfishStartupTimeoutError(
                    path,
                    self._settings.engine_startup_timeout_ms,
                )
                self._log_start_failure(error, started_at)
                raise error from exc
            except Exception as exc:
                if engine is not None:
                    self._close_without_raising(engine)
                error = StockfishStartupError(path)
                self._log_start_failure(error, started_at)
                raise error from exc

            self._engine = engine
            log_event(
                self._logger,
                logging.INFO,
                "stockfish_started",
                duration_ms=(perf_counter() - started_at) * 1_000,
                metadata={
                    "path": path,
                    "skill_level": self._settings.stockfish_skill_level,
                },
            )

    def select_move(self, fen: str, *, game_id: str | None = None) -> chess.Move:
        """Return one legal Stockfish move for a FEN position before the hard deadline."""
        with self._lock:
            error: StockfishError
            engine = self._engine
            if engine is None:
                error = StockfishNotRunningError()
                self._log_move_rejection(error, game_id)
                raise error

            board = self._parse_position(fen, game_id)
            if not any(board.legal_moves):
                error = StockfishNoMoveError()
                self._log_move_rejection(error, game_id)
                raise error

            limit = self.limit
            timeout_seconds = self._settings.engine_move_timeout_ms / 1_000
            started_at = perf_counter()
            log_event(
                self._logger,
                logging.INFO,
                "stockfish_move_requested",
                game_id=game_id,
                metadata=self._move_metadata(limit),
            )

            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stockfish-move")
            future = executor.submit(engine.play, board, limit)
            try:
                result = future.result(timeout=timeout_seconds)
            except FutureTimeoutError as exc:
                self._discard_engine(engine)
                executor.shutdown(wait=False, cancel_futures=True)
                error = StockfishMoveTimeoutError(self._settings.engine_move_timeout_ms)
                self._log_move_failure("stockfish_move_timeout", error, started_at, game_id)
                raise error from exc
            except Exception as exc:
                self._discard_engine(engine)
                executor.shutdown(wait=True, cancel_futures=True)
                error = StockfishMoveError()
                self._log_move_failure("stockfish_move_failed", error, started_at, game_id)
                raise error from exc
            else:
                executor.shutdown(wait=True)

            move = result.move
            if move is None:
                error = StockfishNoMoveError()
                self._discard_engine(engine)
                self._log_move_failure("stockfish_move_failed", error, started_at, game_id)
                raise error
            if move not in board.legal_moves:
                error = StockfishIllegalMoveError(move.uci())
                self._discard_engine(engine)
                self._log_move_failure("stockfish_move_failed", error, started_at, game_id)
                raise error

            log_event(
                self._logger,
                logging.INFO,
                "stockfish_move_selected",
                game_id=game_id,
                duration_ms=(perf_counter() - started_at) * 1_000,
                metadata={"uci": move.uci()},
            )
            return move

    def stop(self) -> None:
        """Shut down the owned engine; repeated calls are safe."""
        with self._lock:
            engine = self._engine
            if engine is None:
                return

            self._engine = None
            started_at = perf_counter()
            try:
                engine.quit()
            except Exception as exc:
                self._close_without_raising(engine)
                error = StockfishShutdownError()
                log_event(
                    self._logger,
                    logging.ERROR,
                    "stockfish_shutdown_failed",
                    duration_ms=(perf_counter() - started_at) * 1_000,
                    error=error,
                )
                raise error from exc

            log_event(
                self._logger,
                logging.INFO,
                "stockfish_stopped",
                duration_ms=(perf_counter() - started_at) * 1_000,
            )

    def _parse_position(self, fen: str, game_id: str | None) -> chess.Board:
        try:
            board = chess.Board(fen)
        except ValueError as exc:
            error = InvalidEnginePositionError()
            self._log_move_rejection(error, game_id)
            raise error from exc

        if not board.is_valid():
            error = InvalidEnginePositionError()
            self._log_move_rejection(error, game_id)
            raise error
        return board

    def _discard_engine(self, engine: UciEngine) -> None:
        if self._engine is engine:
            self._engine = None
        self._close_without_raising(engine)

    @staticmethod
    def _close_without_raising(engine: UciEngine) -> None:
        try:
            engine.close()
        except Exception:
            pass

    def _log_start_failure(self, error: StockfishError, started_at: float) -> None:
        log_event(
            self._logger,
            logging.ERROR,
            "stockfish_start_failed",
            duration_ms=(perf_counter() - started_at) * 1_000,
            metadata={"path": self._settings.stockfish_path},
            error=error,
        )

    def _log_move_rejection(self, error: StockfishError, game_id: str | None) -> None:
        log_event(
            self._logger,
            logging.WARNING,
            "stockfish_move_rejected",
            game_id=game_id,
            error=error,
        )

    def _log_move_failure(
        self,
        event: str,
        error: StockfishError,
        started_at: float,
        game_id: str | None,
    ) -> None:
        log_event(
            self._logger,
            logging.ERROR,
            event,
            game_id=game_id,
            duration_ms=(perf_counter() - started_at) * 1_000,
            error=error,
        )

    def _move_metadata(self, limit: chess.engine.Limit) -> dict[str, object]:
        return {
            "depth": limit.depth,
            "search_time_ms": None if limit.time is None else round(limit.time * 1_000),
            "timeout_ms": self._settings.engine_move_timeout_ms,
        }
