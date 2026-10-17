"""Tests for strict JSON-facing API contracts."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from voicechess.config import Settings
from voicechess.game import GameController
from voicechess.logging import configure_logging, reset_logging
from voicechess.pgn import PgnExportResult
from voicechess.schemas import (
    ErrorResponse,
    GameSnapshotResponse,
    HealthResponse,
    MoveRequest,
    PgnExportResponse,
)

TEST_GAME_ID = UUID("12345678-1234-5678-1234-567812345678")


def test_move_request_strips_san_whitespace() -> None:
    request = MoveRequest.model_validate({"san": "  Nf3  "})

    assert request.san == "Nf3"
    assert request.model_dump(mode="json") == {"san": "Nf3"}


@pytest.mark.parametrize(
    "payload",
    [
        {"san": "   "},
        {"san": "e4", "unexpected": True},
        {},
    ],
)
def test_move_request_rejects_empty_missing_and_extra_data(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MoveRequest.model_validate(payload)


def test_snapshot_response_is_json_ready_and_copies_domain_data(tmp_path: Path) -> None:
    logger = configure_logging(Settings(log_destination=tmp_path / "voicechess.jsonl"))
    try:
        game = GameController(logger=logger, game_id_factory=lambda: TEST_GAME_ID)
        snapshot = game.snapshot()

        response = GameSnapshotResponse.from_snapshot(snapshot)
        response.board["e4"] = "P"
        response.moves.append("e4")

        payload = response.model_dump(mode="json")
        assert payload["game_id"] == str(TEST_GAME_ID)
        assert payload["side_to_move"] == "white"
        assert payload["status"] == "active"
        assert payload["result"] is None
        assert payload["state"] == "PLAYER_INPUT"
        assert snapshot.board.get("e4") is None
        assert snapshot.moves == ()
    finally:
        reset_logging(logger)


@pytest.mark.parametrize(
    "board",
    [
        {"z9": "P"},
        {"e4": "X"},
    ],
)
def test_snapshot_response_rejects_invalid_board_contract(board: dict[str, str]) -> None:
    payload = {
        "game_id": str(TEST_GAME_ID),
        "fen": "valid-for-contract-boundary",
        "side_to_move": "white",
        "board": board,
        "moves": [],
        "status": "active",
        "result": None,
        "last_move": None,
        "message": "White to move.",
        "state": "PLAYER_INPUT",
    }

    with pytest.raises(ValidationError):
        GameSnapshotResponse.model_validate(payload)


def test_health_response_has_stable_wire_values() -> None:
    healthy = HealthResponse(status="ok", stockfish_ready=True)
    degraded = HealthResponse(status="degraded", stockfish_ready=False)

    assert healthy.model_dump(mode="json") == {"status": "ok", "stockfish_ready": True}
    assert degraded.model_dump(mode="json") == {
        "status": "degraded",
        "stockfish_ready": False,
    }


def test_error_response_wraps_safe_code_and_message() -> None:
    response = ErrorResponse.from_error("invalid_move", ValueError("That move is illegal."))

    assert response.model_dump(mode="json") == {
        "error": {"code": "invalid_move", "message": "That move is illegal."}
    }


@pytest.mark.parametrize("code", ["InvalidMove", "invalid-move", "123_error"])
def test_error_response_rejects_unstable_error_codes(code: str) -> None:
    with pytest.raises(ValidationError):
        ErrorResponse.from_error(code, ValueError("failure"))


def test_pgn_export_response_omits_internal_path() -> None:
    result = PgnExportResult(
        game_id=str(TEST_GAME_ID),
        filename=f"game-{TEST_GAME_ID}.pgn",
        path=Path("exports") / f"game-{TEST_GAME_ID}.pgn",
        pgn='[Result "*"]\n\n*\n',
    )

    response = PgnExportResponse.from_result(result)
    payload = response.model_dump(mode="json")

    assert payload == {
        "game_id": str(TEST_GAME_ID),
        "filename": f"game-{TEST_GAME_ID}.pgn",
        "pgn": '[Result "*"]\n\n*\n',
    }
    assert "path" not in payload


def test_api_models_reject_undeclared_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        HealthResponse.model_validate(
            {"status": "ok", "stockfish_ready": True, "internal_path": "secret"}
        )
