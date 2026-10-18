"""Integration tests for the local FastAPI application."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import chess
import pytest
from fastapi.testclient import TestClient

from voicechess.api import ExportService, create_app
from voicechess.config import Settings
from voicechess.engine import StockfishMoveTimeoutError, StockfishStartupError
from voicechess.game import GameSnapshot
from voicechess.logging import configure_logging, reset_logging
from voicechess.pgn import PgnExportResult, PgnWriteError


class FakeEngineService:
    def __init__(self) -> None:
        self.running = False
        self.move = chess.Move.from_uci("e7e5")
        self.start_error: Exception | None = None
        self.move_error: Exception | None = None
        self.start_calls = 0
        self.stop_calls = 0
        self.positions: list[tuple[str, str | None]] = []

    @property
    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.start_calls += 1
        if self.start_error is not None:
            raise self.start_error
        self.running = True

    def select_move(self, fen: str, *, game_id: str | None = None) -> chess.Move:
        self.positions.append((fen, game_id))
        if self.move_error is not None:
            raise self.move_error
        return self.move

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False


class BrokenExporter:
    def export(self, snapshot: GameSnapshot) -> PgnExportResult:
        raise RuntimeError(f"do not expose path for {snapshot.game_id}")


class ControlledBrokenExporter:
    def export(self, snapshot: GameSnapshot) -> PgnExportResult:
        raise PgnWriteError


@dataclass(slots=True)
class ApiTestContext:
    client: TestClient
    engine: FakeEngineService
    settings: Settings
    log_destination: Path


@pytest.fixture
def api_context(tmp_path: Path) -> Iterator[ApiTestContext]:
    log_destination = tmp_path / "voicechess.jsonl"
    settings = Settings(
        log_destination=log_destination,
        pgn_export_dir=tmp_path / "exports",
    )
    logger = configure_logging(settings)
    engine = FakeEngineService()
    app = create_app(settings=settings, logger=logger, engine=engine)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield ApiTestContext(client, engine, settings, log_destination)
    reset_logging(logger)


def read_events(destination: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines()]


def test_lifespan_starts_engine_and_health_reports_ready(
    api_context: ApiTestContext,
) -> None:
    response = api_context.client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "stockfish_ready": True}
    assert api_context.engine.start_calls == 1
    assert "app;dur=" in response.headers["server-timing"]


def test_lifespan_stops_engine_after_client_closes(tmp_path: Path) -> None:
    settings = Settings(log_destination=tmp_path / "voicechess.jsonl")
    logger = configure_logging(settings)
    engine = FakeEngineService()
    app = create_app(settings=settings, logger=logger, engine=engine)

    with TestClient(app):
        assert engine.is_running

    assert not engine.is_running
    assert engine.stop_calls == 1
    reset_logging(logger)


def test_browser_shell_and_local_assets_are_served(api_context: ApiTestContext) -> None:
    page = api_context.client.get("/")
    css = api_context.client.get("/static/app.css")
    javascript = api_context.client.get("/static/app.js")

    assert page.status_code == 200
    assert "Adaptive Chess Teacher" in page.text
    assert 'id="chessboard"' in page.text
    assert 'id="manual-mode-button"' in page.text
    assert 'id="voice-mode-button"' in page.text
    assert 'id="promotion-dialog"' in page.text
    assert css.status_code == 200
    assert ".chessboard" in css.text
    assert javascript.status_code == 200
    assert 'requestJson("/api/game/move"' in javascript.text


def test_current_game_returns_complete_initial_snapshot(api_context: ApiTestContext) -> None:
    response = api_context.client.get("/api/game")
    payload = response.json()

    assert response.status_code == 200
    assert len(payload["board"]) == 32
    assert payload["board"]["e1"] == "K"
    assert payload["side_to_move"] == "white"
    assert payload["moves"] == []
    assert payload["state"] == "PLAYER_INPUT"


def test_valid_san_runs_complete_player_and_engine_turn(api_context: ApiTestContext) -> None:
    response = api_context.client.post("/api/game/move", json={"san": "e4"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["moves"] == ["e4", "e5"]
    assert payload["board"]["e4"] == "P"
    assert payload["board"]["e5"] == "p"
    assert payload["state"] == "PLAYER_INPUT"
    assert len(api_context.engine.positions) == 1
    engine_board = chess.Board(api_context.engine.positions[0][0])
    assert engine_board.piece_at(chess.E4) == chess.Piece(chess.PAWN, chess.WHITE)


def test_valid_board_move_runs_complete_player_and_engine_turn(
    api_context: ApiTestContext,
) -> None:
    response = api_context.client.post(
        "/api/game/move",
        json={"from_square": "e2", "to_square": "e4", "promotion": None},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["moves"] == ["e4", "e5"]
    assert payload["board"]["e4"] == "P"
    assert payload["state"] == "PLAYER_INPUT"


def test_illegal_board_move_returns_piece_to_original_position(
    api_context: ApiTestContext,
) -> None:
    response = api_context.client.post(
        "/api/game/move",
        json={"from_square": "e2", "to_square": "e5"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "illegal_move"
    snapshot = api_context.client.get("/api/game").json()
    assert snapshot["board"]["e2"] == "P"
    assert "e5" not in snapshot["board"]
    assert snapshot["moves"] == []


@pytest.mark.parametrize(
    ("san", "error_code"),
    [("horse to e4", "invalid_san"), ("e5", "illegal_move")],
)
def test_rejected_san_returns_controlled_error_and_preserves_game(
    api_context: ApiTestContext,
    san: str,
    error_code: str,
) -> None:
    response = api_context.client.post("/api/game/move", json={"san": san})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == error_code
    snapshot = api_context.client.get("/api/game").json()
    assert snapshot["moves"] == []
    assert snapshot["state"] == "PLAYER_INPUT"


def test_invalid_request_uses_error_envelope(api_context: ApiTestContext) -> None:
    response = api_context.client.post("/api/game/move", json={"san": "   ", "extra": True})

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "invalid_request", "message": "The request is invalid."}
    }


def test_engine_timeout_rolls_back_player_move(api_context: ApiTestContext) -> None:
    api_context.engine.move_error = StockfishMoveTimeoutError(100)

    response = api_context.client.post("/api/game/move", json={"san": "e4"})

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "stockfish_timeout"
    snapshot = api_context.client.get("/api/game").json()
    assert snapshot["moves"] == []
    assert snapshot["board"]["e2"] == "P"
    assert "e4" not in snapshot["board"]
    assert snapshot["state"] == "PLAYER_INPUT"


def test_illegal_engine_move_rolls_back_player_move(api_context: ApiTestContext) -> None:
    api_context.engine.move = chess.Move.from_uci("e7e4")

    response = api_context.client.post("/api/game/move", json={"san": "e4"})

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "illegal_engine_move"
    snapshot = api_context.client.get("/api/game").json()
    assert snapshot["moves"] == []
    assert snapshot["state"] == "PLAYER_INPUT"


def test_unavailable_engine_keeps_health_and_move_failure_safe(tmp_path: Path) -> None:
    settings = Settings(log_destination=tmp_path / "voicechess.jsonl")
    logger = configure_logging(settings)
    engine = FakeEngineService()
    engine.start_error = StockfishStartupError("missing-stockfish")
    app = create_app(settings=settings, logger=logger, engine=engine)

    with TestClient(app, raise_server_exceptions=False) as client:
        health = client.get("/api/health")
        illegal_move = client.post("/api/game/move", json={"san": "e5"})
        move = client.post("/api/game/move", json={"san": "e4"})
        snapshot = client.get("/api/game").json()

    assert health.status_code == 503
    assert health.json() == {"status": "degraded", "stockfish_ready": False}
    assert illegal_move.status_code == 400
    assert illegal_move.json()["error"]["code"] == "illegal_move"
    assert move.status_code == 503
    assert move.json()["error"]["code"] == "stockfish_unavailable"
    assert snapshot["moves"] == []
    reset_logging(logger)


def test_new_game_and_resignation_routes_return_snapshots(api_context: ApiTestContext) -> None:
    original_id = api_context.client.get("/api/game").json()["game_id"]
    resigned = api_context.client.post("/api/game/resign").json()
    replacement = api_context.client.post("/api/game/new").json()

    assert resigned["status"] == "resigned"
    assert resigned["result"] == "0-1"
    assert resigned["state"] == "GAME_OVER"
    assert replacement["status"] == "active"
    assert replacement["game_id"] != original_id
    assert replacement["moves"] == []


def test_finished_game_rejects_further_actions(api_context: ApiTestContext) -> None:
    api_context.client.post("/api/game/resign")

    move = api_context.client.post("/api/game/move", json={"san": "e4"})
    resign = api_context.client.post("/api/game/resign")

    assert move.status_code == 409
    assert move.json()["error"]["code"] == "game_not_active"
    assert resign.status_code == 409
    assert resign.json()["error"]["code"] == "game_not_active"


def test_export_route_returns_download_data_and_writes_file(api_context: ApiTestContext) -> None:
    api_context.client.post("/api/game/move", json={"san": "e4"})

    response = api_context.client.post("/api/game/export")
    payload = response.json()

    assert response.status_code == 200
    assert payload["filename"].endswith(".pgn")
    assert '[White "Player"]' in payload["pgn"]
    assert "1. e4 e5 *" in payload["pgn"]
    assert (api_context.settings.pgn_export_dir / payload["filename"]).exists()
    assert "path" not in payload


def test_unexpected_errors_return_generic_message_without_leaking_details(tmp_path: Path) -> None:
    log_destination = tmp_path / "voicechess.jsonl"
    settings = Settings(log_destination=log_destination)
    logger = configure_logging(settings)
    engine = FakeEngineService()
    exporter: ExportService = BrokenExporter()
    app = create_app(settings=settings, logger=logger, engine=engine, pgn=exporter)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/game/export")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected application error occurred.",
        }
    }
    assert "do not expose" not in response.text
    unexpected = next(
        event
        for event in read_events(log_destination)
        if event["event"] == "unexpected_application_error"
    )
    assert unexpected["game_id"]
    assert unexpected["error"]["type"] == "RuntimeError"
    reset_logging(logger)


def test_controlled_pgn_failure_uses_stable_error_envelope(tmp_path: Path) -> None:
    settings = Settings(log_destination=tmp_path / "voicechess.jsonl")
    logger = configure_logging(settings)
    engine = FakeEngineService()
    exporter: ExportService = ControlledBrokenExporter()
    app = create_app(settings=settings, logger=logger, engine=engine, pgn=exporter)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/game/export")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "pgn_export_failed",
            "message": "The PGN file could not be written.",
        }
    }
    reset_logging(logger)


def test_http_requests_are_timed_in_structured_logs(api_context: ApiTestContext) -> None:
    api_context.client.get("/api/game")

    event = read_events(api_context.log_destination)[-1]
    assert event["event"] == "http_request_completed"
    assert event["game_id"]
    assert event["metadata"] == {"method": "GET", "path": "/api/game", "status": 200}
    assert event["duration_ms"] >= 0
