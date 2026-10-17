"""Validated, atomic PGN export from immutable game snapshots."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter

import chess
import chess.pgn

from voicechess.config import Settings
from voicechess.game import GameSnapshot
from voicechess.logging import log_event
from voicechess.pgn.errors import (
    InconsistentGameSnapshotError,
    InvalidGameHistoryError,
    InvalidPgnError,
    PgnExportError,
    PgnWriteError,
)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class PgnExportResult:
    """Information and content produced by one successful export."""

    game_id: str
    filename: str
    path: Path
    pgn: str


class PgnExporter:
    """Reconstruct, validate, and atomically persist standard PGN files."""

    def __init__(
        self,
        *,
        settings: Settings,
        logger: logging.Logger,
        clock: Clock = utc_now,
    ) -> None:
        self._destination = settings.pgn_export_dir
        self._logger = logger
        self._clock = clock

    def export(self, snapshot: GameSnapshot) -> PgnExportResult:
        """Write a validated PGN for one immutable game snapshot."""
        started_at = perf_counter()
        try:
            game = self._build_game(snapshot)
            pgn = self._render_and_validate(game, snapshot)
            filename = self._filename(snapshot.game_id)
            path = self._write_atomically(filename, pgn)
        except PgnExportError as error:
            self._log_failure(snapshot.game_id, error, started_at)
            raise
        except OSError as exc:
            write_error = PgnWriteError()
            self._log_failure(snapshot.game_id, write_error, started_at)
            raise write_error from exc

        log_event(
            self._logger,
            logging.INFO,
            "pgn_exported",
            game_id=snapshot.game_id,
            duration_ms=(perf_counter() - started_at) * 1_000,
            metadata={"filename": filename, "result": game.headers["Result"]},
        )
        return PgnExportResult(
            game_id=snapshot.game_id,
            filename=filename,
            path=path,
            pgn=pgn,
        )

    def _build_game(self, snapshot: GameSnapshot) -> chess.pgn.Game:
        game = chess.pgn.Game()
        exported_at = self._clock()
        game.headers.update(
            {
                "Event": "Adaptive Chess Teacher Game",
                "Site": "Local",
                "Date": exported_at.strftime("%Y.%m.%d"),
                "Round": "-",
                "White": "Player",
                "Black": "Stockfish",
                "Result": "*" if snapshot.result is None else snapshot.result.value,
            }
        )

        board = game.board()
        node: chess.pgn.GameNode = game
        for ply, san in enumerate(snapshot.moves, start=1):
            try:
                move = board.parse_san(san)
            except ValueError as exc:
                raise InvalidGameHistoryError(ply, san) from exc
            node = node.add_variation(move)
            board.push(move)

        if board.fen() != snapshot.fen:
            raise InconsistentGameSnapshotError()
        return game

    def _render_and_validate(self, game: chess.pgn.Game, snapshot: GameSnapshot) -> str:
        exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
        pgn = game.accept(exporter).rstrip() + "\n"
        parsed = chess.pgn.read_game(StringIO(pgn))
        expected_result = "*" if snapshot.result is None else snapshot.result.value
        if (
            parsed is None
            or parsed.errors
            or parsed.headers.get("Result") != expected_result
            or parsed.end().board().fen() != snapshot.fen
        ):
            raise InvalidPgnError()
        return pgn

    def _write_atomically(self, filename: str, pgn: str) -> Path:
        self._destination.mkdir(parents=True, exist_ok=True)
        destination = self._destination / filename
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{filename}.",
                suffix=".tmp",
                dir=self._destination,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(pgn)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            temporary_path.replace(destination)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        return destination

    @staticmethod
    def _filename(game_id: str) -> str:
        safe_game_id = re.sub(r"[^A-Za-z0-9_-]", "_", game_id).strip("_-")
        if not safe_game_id:
            safe_game_id = "game"
        return f"game-{safe_game_id}.pgn"

    def _log_failure(
        self,
        game_id: str,
        error: PgnExportError,
        started_at: float,
    ) -> None:
        log_event(
            self._logger,
            logging.ERROR,
            "pgn_export_failed",
            game_id=game_id,
            duration_ms=(perf_counter() - started_at) * 1_000,
            error=error,
        )
