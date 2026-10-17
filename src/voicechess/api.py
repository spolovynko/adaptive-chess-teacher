"""FastAPI composition root and local HTTP routes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Protocol

import chess
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHttpException

from voicechess.config import Settings, get_settings
from voicechess.engine import (
    StockfishError,
    StockfishMoveTimeoutError,
    StockfishNotRunningError,
    StockfishService,
    StockfishStartupError,
)
from voicechess.game import (
    EmptySanError,
    EngineMoveNotExpectedError,
    GameController,
    GameError,
    GameNotActiveError,
    IllegalEngineMoveError,
    IllegalSanMoveError,
    InvalidSanError,
    MoveInputError,
    PlayerMoveNotExpectedError,
)
from voicechess.game.models import GameStatus
from voicechess.game.snapshot import GameSnapshot
from voicechess.logging import configure_logging, log_event, reset_logging
from voicechess.pgn import PgnExporter, PgnExportError, PgnExportResult
from voicechess.schemas import (
    ErrorResponse,
    GameSnapshotResponse,
    HealthResponse,
    MoveRequest,
    PgnExportResponse,
)

PACKAGE_DIRECTORY = Path(__file__).resolve().parent
STATIC_DIRECTORY = PACKAGE_DIRECTORY / "static"
INDEX_PATH = PACKAGE_DIRECTORY / "templates" / "index.html"


class EngineService(Protocol):
    """Engine behavior required by the HTTP application."""

    @property
    def is_running(self) -> bool:
        """Return whether the engine is ready."""

    def start(self) -> None:
        """Start the engine if needed."""

    def select_move(self, fen: str, *, game_id: str | None = None) -> chess.Move:
        """Select a legal move for a position."""

    def stop(self) -> None:
        """Stop the engine if running."""


class ExportService(Protocol):
    """PGN behavior required by the HTTP application."""

    def export(self, snapshot: GameSnapshot) -> PgnExportResult:
        """Export a domain snapshot."""


@dataclass(slots=True)
class ApplicationServices:
    """Long-lived local services shared by HTTP requests."""

    settings: Settings
    logger: logging.Logger
    game: GameController
    engine: EngineService
    pgn: ExportService
    game_lock: RLock = field(default_factory=RLock)


def create_app(
    *,
    settings: Settings | None = None,
    logger: logging.Logger | None = None,
    engine: EngineService | None = None,
    game: GameController | None = None,
    pgn: ExportService | None = None,
) -> FastAPI:
    """Build the local application with injectable services for deterministic tests."""
    active_settings = settings or get_settings()
    owns_logger = logger is None
    active_logger = logger or configure_logging(active_settings)
    services = ApplicationServices(
        settings=active_settings,
        logger=active_logger,
        game=game or GameController(logger=active_logger),
        engine=engine or StockfishService(settings=active_settings, logger=active_logger),
        pgn=pgn or PgnExporter(settings=active_settings, logger=active_logger),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            await asyncio.to_thread(services.engine.start)
        except StockfishError:
            pass
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(services.engine.stop)
            except StockfishError:
                pass
            finally:
                if owns_logger:
                    reset_logging(active_logger)

    app = FastAPI(
        title="Adaptive Chess Teacher",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.services = services
    app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")

    @app.middleware("http")
    async def log_http_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started_at = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            log_event(
                active_logger,
                logging.ERROR,
                "http_request_completed",
                duration_ms=(perf_counter() - started_at) * 1_000,
                metadata={"method": request.method, "path": request.url.path, "status": 500},
                error=exc,
            )
            raise

        duration_ms = (perf_counter() - started_at) * 1_000
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.3f}"
        log_event(
            active_logger,
            logging.INFO,
            "http_request_completed",
            duration_ms=duration_ms,
            metadata={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
            },
        )
        return response

    @app.exception_handler(GameError)
    async def handle_game_error(_: Request, error: GameError) -> JSONResponse:
        status_code, code = _game_error_response(error)
        return _error_response(status_code, code, error)

    @app.exception_handler(StockfishError)
    async def handle_stockfish_error(_: Request, error: StockfishError) -> JSONResponse:
        status_code, code = _stockfish_error_response(error)
        return _error_response(status_code, code, error)

    @app.exception_handler(PgnExportError)
    async def handle_pgn_error(_: Request, error: PgnExportError) -> JSONResponse:
        return _error_response(500, "pgn_export_failed", error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error_response(422, "invalid_request", ValueError("The request is invalid."))

    @app.exception_handler(StarletteHttpException)
    async def handle_http_error(_: Request, error: StarletteHttpException) -> JSONResponse:
        message = (
            error.detail if isinstance(error.detail, str) else "The request could not be completed."
        )
        return _error_response(error.status_code, "http_error", ValueError(message))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, error: Exception) -> JSONResponse:
        log_event(active_logger, logging.ERROR, "unexpected_application_error", error=error)
        return _error_response(
            500,
            "internal_error",
            RuntimeError("An unexpected application error occurred."),
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(INDEX_PATH, media_type="text/html")

    @app.get("/api/health", response_model=HealthResponse)
    def health(response: Response) -> HealthResponse:
        ready = services.engine.is_running
        if not ready:
            response.status_code = 503
        return HealthResponse(
            status="ok" if ready else "degraded",
            stockfish_ready=ready,
        )

    @app.get("/api/game", response_model=GameSnapshotResponse)
    def current_game() -> GameSnapshotResponse:
        with services.game_lock:
            return GameSnapshotResponse.from_snapshot(services.game.snapshot())

    @app.post("/api/game/new", response_model=GameSnapshotResponse)
    def new_game() -> GameSnapshotResponse:
        with services.game_lock:
            return GameSnapshotResponse.from_snapshot(services.game.new_game())

    @app.post("/api/game/move", response_model=GameSnapshotResponse)
    def submit_move(request: MoveRequest) -> GameSnapshotResponse:
        with services.game_lock:
            services.game.submit_player_san(request.san)
            if services.game.status is not GameStatus.ACTIVE:
                return GameSnapshotResponse.from_snapshot(services.game.snapshot())

            try:
                if not services.engine.is_running:
                    services.engine.start()
                move = services.engine.select_move(
                    services.game.fen,
                    game_id=services.game.game_id,
                )
                services.game.apply_engine_move(move)
            except (StockfishError, IllegalEngineMoveError):
                services.game.recover_from_engine_failure()
                raise

            return GameSnapshotResponse.from_snapshot(services.game.snapshot())

    @app.post("/api/game/resign", response_model=GameSnapshotResponse)
    def resign() -> GameSnapshotResponse:
        with services.game_lock:
            services.game.resign()
            return GameSnapshotResponse.from_snapshot(services.game.snapshot())

    @app.post("/api/game/export", response_model=PgnExportResponse)
    def export_game() -> PgnExportResponse:
        with services.game_lock:
            snapshot = services.game.snapshot()
        return PgnExportResponse.from_result(services.pgn.export(snapshot))

    return app


def _error_response(status_code: int, code: str, error: BaseException) -> JSONResponse:
    payload = ErrorResponse.from_error(code, error).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


def _game_error_response(error: GameError) -> tuple[int, str]:
    if isinstance(error, EmptySanError):
        return 400, "empty_san"
    if isinstance(error, InvalidSanError):
        return 400, "invalid_san"
    if isinstance(error, IllegalSanMoveError):
        return 400, "illegal_move"
    if isinstance(error, MoveInputError):
        return 400, "invalid_move"
    if isinstance(error, GameNotActiveError):
        return 409, "game_not_active"
    if isinstance(error, PlayerMoveNotExpectedError):
        return 409, "player_move_not_expected"
    if isinstance(error, EngineMoveNotExpectedError):
        return 409, "engine_move_not_expected"
    if isinstance(error, IllegalEngineMoveError):
        return 502, "illegal_engine_move"
    return 400, "game_error"


def _stockfish_error_response(error: StockfishError) -> tuple[int, str]:
    if isinstance(error, StockfishMoveTimeoutError):
        return 504, "stockfish_timeout"
    if isinstance(error, StockfishNotRunningError | StockfishStartupError):
        return 503, "stockfish_unavailable"
    return 502, "stockfish_error"


__all__ = ["ApplicationServices", "EngineService", "create_app"]
