"""Tests for the bounded local Stockfish process service."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from threading import Event

import chess
import chess.engine
import pytest

from voicechess.config import Settings
from voicechess.engine import (
    InvalidEnginePositionError,
    StockfishIllegalMoveError,
    StockfishMoveError,
    StockfishMoveTimeoutError,
    StockfishNoMoveError,
    StockfishNotRunningError,
    StockfishService,
    StockfishShutdownError,
    StockfishStartupError,
    StockfishStartupTimeoutError,
    UciEngine,
)
from voicechess.game import GameController
from voicechess.logging import configure_logging, reset_logging


class FakeEngine:
    """Small controllable implementation of the service's UCI protocol."""

    def __init__(self, move: chess.Move | None = None) -> None:
        self.timeout: float | None = None
        self.move = move
        self.configure_error: Exception | None = None
        self.play_error: Exception | None = None
        self.quit_error: Exception | None = None
        self.block_during_play = False
        self.closed = Event()
        self.configurations: list[dict[str, str | int | bool | None]] = []
        self.play_boards: list[chess.Board] = []
        self.play_limits: list[chess.engine.Limit] = []
        self.quit_calls = 0
        self.close_calls = 0

    def configure(self, options: chess.engine.ConfigMapping) -> None:
        self.configurations.append(dict(options))
        if self.configure_error is not None:
            raise self.configure_error

    def play(self, board: chess.Board, limit: chess.engine.Limit) -> chess.engine.PlayResult:
        self.play_boards.append(board.copy(stack=True))
        self.play_limits.append(limit)
        if self.block_during_play:
            self.closed.wait(timeout=2)
        if self.play_error is not None:
            raise self.play_error
        return chess.engine.PlayResult(self.move, None)

    def quit(self) -> None:
        self.quit_calls += 1
        if self.quit_error is not None:
            raise self.quit_error

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


class FakeEngineFactory:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine
        self.error: Exception | None = None
        self.calls: list[tuple[str, float]] = []

    def __call__(self, path: str, timeout_seconds: float) -> UciEngine:
        self.calls.append((path, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.engine


@pytest.fixture
def logger_and_destination(tmp_path: Path) -> Iterator[tuple[logging.Logger, Path]]:
    destination = tmp_path / "voicechess.jsonl"
    logger = configure_logging(Settings(log_destination=destination))
    yield logger, destination
    reset_logging(logger)


def read_events(destination: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]


def settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "log_destination": tmp_path / "unused.jsonl",
        "stockfish_path": "stockfish-test",
    }
    values.update(overrides)
    return Settings(**values)


def started_service(
    tmp_path: Path,
    logger: logging.Logger,
    engine: FakeEngine,
    **setting_overrides: object,
) -> tuple[StockfishService, FakeEngineFactory]:
    factory = FakeEngineFactory(engine)
    service = StockfishService(
        settings=settings(tmp_path, **setting_overrides),
        logger=logger,
        engine_factory=factory,
    )
    service.start()
    return service, factory


def test_move_requires_a_running_engine(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    service = StockfishService(settings=settings(tmp_path), logger=logger)

    with pytest.raises(StockfishNotRunningError):
        service.select_move(chess.STARTING_FEN, game_id="game-123")

    event = read_events(destination)[-1]
    assert event["event"] == "stockfish_move_rejected"
    assert event["game_id"] == "game-123"


def test_start_uses_configured_path_timeout_and_skill_and_is_idempotent(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    engine = FakeEngine()
    factory = FakeEngineFactory(engine)
    service = StockfishService(
        settings=settings(
            tmp_path,
            stockfish_skill_level=7,
            engine_startup_timeout_ms=1_250,
            engine_move_timeout_ms=2_500,
        ),
        logger=logger,
        engine_factory=factory,
    )

    service.start()
    service.start()

    assert service.is_running
    assert factory.calls == [("stockfish-test", 1.25)]
    assert engine.configurations == [{"Skill Level": 7}]
    assert engine.timeout == 2.5
    events = read_events(destination)
    assert [event["event"] for event in events] == ["stockfish_starting", "stockfish_started"]
    assert events[-1]["metadata"] == {"path": "stockfish-test", "skill_level": 7}


def test_select_move_uses_fen_and_configured_search_limits(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    chess_board = chess.Board()
    chess_board.push_san("e4")
    engine = FakeEngine(chess.Move.from_uci("e7e5"))
    service, _ = started_service(
        tmp_path,
        logger,
        engine,
        engine_search_depth=12,
        engine_move_time_ms=250,
    )

    move = service.select_move(chess_board.fen(), game_id="game-123")

    assert move == chess.Move.from_uci("e7e5")
    assert engine.play_boards[0].fen() == chess_board.fen()
    assert engine.play_limits[0].depth == 12
    assert engine.play_limits[0].time == 0.25
    events = read_events(destination)
    assert events[-2]["event"] == "stockfish_move_requested"
    assert events[-2]["metadata"] == {
        "depth": 12,
        "search_time_ms": 250,
        "timeout_ms": 10_000,
    }
    assert events[-1]["event"] == "stockfish_move_selected"
    assert events[-1]["metadata"] == {"uci": "e7e5"}


def test_selected_move_integrates_with_game_controller(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    engine = FakeEngine(chess.Move.from_uci("e7e5"))
    service, _ = started_service(tmp_path, logger, engine)
    game = GameController(logger=logger)
    game.submit_player_san("e4")

    game.apply_engine_move(service.select_move(game.fen, game_id=game.game_id))

    assert game.moves == ("e4", "e5")
    assert game.snapshot().board["e5"] == "p"


@pytest.mark.parametrize(
    "fen",
    [
        "not-a-fen",
        "8/8/8/8/8/8/8/8 w - - 0 1",
    ],
)
def test_invalid_position_is_rejected_before_engine_call(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
    fen: str,
) -> None:
    logger, _ = logger_and_destination
    engine = FakeEngine()
    service, _ = started_service(tmp_path, logger, engine)

    with pytest.raises(InvalidEnginePositionError):
        service.select_move(fen)

    assert engine.play_boards == []
    assert service.is_running


def test_terminal_position_is_rejected_before_engine_call(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    board = chess.Board()
    for san in ("f3", "e5", "g4", "Qh4#"):
        board.push_san(san)
    engine = FakeEngine()
    service, _ = started_service(tmp_path, logger, engine)

    with pytest.raises(StockfishNoMoveError):
        service.select_move(board.fen())

    assert engine.play_boards == []
    assert service.is_running


@pytest.mark.parametrize(
    ("move", "error_type"),
    [
        (None, StockfishNoMoveError),
        (chess.Move.from_uci("e7e4"), StockfishIllegalMoveError),
    ],
)
def test_invalid_engine_result_is_rejected_and_engine_is_discarded(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
    move: chess.Move | None,
    error_type: type[Exception],
) -> None:
    logger, destination = logger_and_destination
    board = chess.Board()
    board.push_san("e4")
    engine = FakeEngine(move)
    service, _ = started_service(tmp_path, logger, engine)

    with pytest.raises(error_type):
        service.select_move(board.fen())

    assert not service.is_running
    assert engine.close_calls == 1
    assert read_events(destination)[-1]["event"] == "stockfish_move_failed"


def test_engine_play_failure_is_wrapped_and_engine_is_discarded(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    engine = FakeEngine()
    engine.play_error = chess.engine.EngineTerminatedError("engine exited")
    service, _ = started_service(tmp_path, logger, engine)

    with pytest.raises(StockfishMoveError) as caught:
        service.select_move(chess.STARTING_FEN)

    assert isinstance(caught.value.__cause__, chess.engine.EngineTerminatedError)
    assert not service.is_running
    assert engine.close_calls == 1
    assert read_events(destination)[-1]["event"] == "stockfish_move_failed"


def test_move_timeout_closes_and_invalidates_engine(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    engine = FakeEngine(chess.Move.from_uci("e2e4"))
    engine.block_during_play = True
    service, _ = started_service(
        tmp_path,
        logger,
        engine,
        engine_move_timeout_ms=100,
    )

    with pytest.raises(StockfishMoveTimeoutError, match="within 100 ms"):
        service.select_move(chess.STARTING_FEN, game_id="game-123")

    assert not service.is_running
    assert engine.close_calls == 1
    event = read_events(destination)[-1]
    assert event["event"] == "stockfish_move_timeout"
    assert event["game_id"] == "game-123"


@pytest.mark.parametrize(
    ("factory_error", "error_type"),
    [
        (FileNotFoundError("missing"), StockfishStartupError),
        (TimeoutError("slow startup"), StockfishStartupTimeoutError),
    ],
)
def test_startup_failure_is_wrapped_and_logged(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
    factory_error: Exception,
    error_type: type[Exception],
) -> None:
    logger, destination = logger_and_destination
    engine = FakeEngine()
    factory = FakeEngineFactory(engine)
    factory.error = factory_error
    service = StockfishService(
        settings=settings(tmp_path),
        logger=logger,
        engine_factory=factory,
    )

    with pytest.raises(error_type):
        service.start()

    assert not service.is_running
    event = read_events(destination)[-1]
    assert event["event"] == "stockfish_start_failed"
    assert event["level"] == "ERROR"


def test_configuration_failure_closes_partially_started_engine(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    engine = FakeEngine()
    engine.configure_error = chess.engine.EngineError("unsupported option")
    factory = FakeEngineFactory(engine)
    service = StockfishService(
        settings=settings(tmp_path),
        logger=logger,
        engine_factory=factory,
    )

    with pytest.raises(StockfishStartupError):
        service.start()

    assert not service.is_running
    assert engine.close_calls == 1


def test_stop_quits_engine_and_is_safe_to_repeat(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    engine = FakeEngine()
    service, _ = started_service(tmp_path, logger, engine)

    service.stop()
    service.stop()

    assert not service.is_running
    assert engine.quit_calls == 1
    assert [event["event"] for event in read_events(destination)][-1] == "stockfish_stopped"


def test_shutdown_failure_force_closes_and_invalidates_engine(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    engine = FakeEngine()
    engine.quit_error = TimeoutError("quit timeout")
    service, _ = started_service(tmp_path, logger, engine)

    with pytest.raises(StockfishShutdownError):
        service.stop()

    assert not service.is_running
    assert engine.close_calls == 1
    assert read_events(destination)[-1]["event"] == "stockfish_shutdown_failed"
