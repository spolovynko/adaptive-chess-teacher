"""Tests for validated and atomic PGN export."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import chess
import chess.pgn
import pytest

from voicechess.config import Settings
from voicechess.game import GameController, GameSnapshot
from voicechess.logging import configure_logging, reset_logging
from voicechess.pgn import (
    InconsistentGameSnapshotError,
    InvalidGameHistoryError,
    PgnExporter,
    PgnWriteError,
)

TEST_GAME_ID = UUID("12345678-1234-5678-1234-567812345678")


@pytest.fixture
def logger_and_destination(tmp_path: Path) -> Iterator[tuple[logging.Logger, Path]]:
    destination = tmp_path / "voicechess.jsonl"
    logger = configure_logging(Settings(log_destination=destination))
    yield logger, destination
    reset_logging(logger)


def read_events(destination: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]


def make_exporter(tmp_path: Path, logger: logging.Logger) -> PgnExporter:
    return PgnExporter(
        settings=Settings(pgn_export_dir=tmp_path / "exports"),
        logger=logger,
        clock=lambda: datetime(2026, 10, 17, 12, 30, tzinfo=UTC),
    )


def make_game(logger: logging.Logger) -> GameController:
    return GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)


def read_pgn(path: Path) -> chess.pgn.Game:
    with path.open(encoding="utf-8") as pgn_file:
        game = chess.pgn.read_game(pgn_file)
    assert game is not None
    assert game.errors == []
    return game


def mainline_san(game: chess.pgn.Game) -> list[str]:
    board = game.board()
    moves: list[str] = []
    for move in game.mainline_moves():
        moves.append(board.san(move))
        board.push(move)
    return moves


def test_active_game_exports_standard_headers_and_valid_pgn(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    snapshot = make_game(logger).snapshot()

    result = make_exporter(tmp_path, logger).export(snapshot)

    assert result.game_id == str(TEST_GAME_ID)
    assert result.filename == f"game-{TEST_GAME_ID}.pgn"
    assert result.path == tmp_path / "exports" / result.filename
    assert result.path.read_text(encoding="utf-8") == result.pgn
    parsed = read_pgn(result.path)
    assert parsed.headers["Event"] == "Adaptive Chess Teacher Game"
    assert parsed.headers["Site"] == "Local"
    assert parsed.headers["Date"] == "2026.10.17"
    assert parsed.headers["White"] == "Player"
    assert parsed.headers["Black"] == "Stockfish"
    assert parsed.headers["Result"] == "*"
    assert mainline_san(parsed) == []
    event = read_events(destination)[-1]
    assert event["event"] == "pgn_exported"
    assert event["game_id"] == str(TEST_GAME_ID)
    assert event["metadata"] == {"filename": result.filename, "result": "*"}


def test_move_history_and_final_position_round_trip_through_pgn(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = make_game(logger)
    game.submit_player_san("e4")
    game.apply_engine_move(chess.Move.from_uci("e7e5"))
    game.submit_player_san("Nf3")
    snapshot = game.snapshot()

    result = make_exporter(tmp_path, logger).export(snapshot)
    parsed = read_pgn(result.path)

    assert mainline_san(parsed) == ["e4", "e5", "Nf3"]
    assert parsed.end().board().fen() == snapshot.fen
    assert parsed.headers["Result"] == "*"


def test_checkmate_exports_winner_and_reconstructs_final_position(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = make_game(logger)
    game.submit_player_san("e4")
    game.apply_engine_move(chess.Move.from_uci("e7e5"))
    game.submit_player_san("Qh5")
    game.apply_engine_move(chess.Move.from_uci("b8c6"))
    game.submit_player_san("Bc4")
    game.apply_engine_move(chess.Move.from_uci("g8f6"))
    game.submit_player_san("Qxf7#")
    snapshot = game.snapshot()

    parsed = read_pgn(make_exporter(tmp_path, logger).export(snapshot).path)

    assert parsed.headers["Result"] == "1-0"
    assert parsed.end().board().fen() == snapshot.fen
    assert mainline_san(parsed)[-1] == "Qxf7#"


def test_resignation_exports_black_win_without_changing_position(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = make_game(logger)
    game.submit_player_san("e4")
    game.apply_engine_move(chess.Move.from_uci("e7e5"))
    game.resign()
    snapshot = game.snapshot()

    parsed = read_pgn(make_exporter(tmp_path, logger).export(snapshot).path)

    assert parsed.headers["Result"] == "0-1"
    assert mainline_san(parsed) == ["e4", "e5"]
    assert parsed.end().board().fen() == snapshot.fen


def test_game_ids_are_sanitized_and_produce_distinct_filenames(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    snapshot = make_game(logger).snapshot()
    exporter = make_exporter(tmp_path, logger)

    first = exporter.export(replace(snapshot, game_id="game/one"))
    second = exporter.export(replace(snapshot, game_id="game:two"))

    assert first.filename == "game-game_one.pgn"
    assert second.filename == "game-game_two.pgn"
    assert first.path != second.path
    assert first.path.exists()
    assert second.path.exists()


def test_repeated_export_atomically_replaces_same_game_file(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = make_game(logger)
    exporter = make_exporter(tmp_path, logger)
    initial = exporter.export(game.snapshot())
    game.submit_player_san("e4")

    updated = exporter.export(game.snapshot())

    assert updated.path == initial.path
    assert updated.path.read_text(encoding="utf-8") == updated.pgn
    assert updated.pgn != initial.pgn
    assert list(updated.path.parent.glob("*.tmp")) == []


def test_invalid_san_history_is_rejected_without_writing_file(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    snapshot = replace(make_game(logger).snapshot(), moves=("e5",))
    exporter = make_exporter(tmp_path, logger)

    with pytest.raises(InvalidGameHistoryError):
        exporter.export(snapshot)

    assert not (tmp_path / "exports").exists()
    assert read_events(destination)[-1]["event"] == "pgn_export_failed"


def test_history_that_disagrees_with_fen_is_rejected(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, _ = logger_and_destination
    game = make_game(logger)
    game.submit_player_san("e4")
    snapshot: GameSnapshot = replace(game.snapshot(), moves=())

    with pytest.raises(InconsistentGameSnapshotError):
        make_exporter(tmp_path, logger).export(snapshot)


def test_write_failure_is_controlled_and_logged(
    tmp_path: Path,
    logger_and_destination: tuple[logging.Logger, Path],
) -> None:
    logger, destination = logger_and_destination
    blocked_destination = tmp_path / "blocked"
    blocked_destination.write_text("not a directory", encoding="utf-8")
    exporter = PgnExporter(
        settings=Settings(pgn_export_dir=blocked_destination),
        logger=logger,
    )

    with pytest.raises(PgnWriteError) as caught:
        exporter.export(make_game(logger).snapshot())

    assert isinstance(caught.value.__cause__, OSError)
    event = read_events(destination)[-1]
    assert event["event"] == "pgn_export_failed"
    assert event["level"] == "ERROR"
    assert "duration_ms" in event
