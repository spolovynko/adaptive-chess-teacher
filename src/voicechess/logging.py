"""Structured, append-only JSON Lines logging for the application."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from voicechess.config import Settings

LOGGER_NAME = "voicechess"


class JsonLinesFormatter(logging.Formatter):
    """Format every logging record as one self-contained JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
            "logger": record.name,
        }

        for field in ("game_id", "duration_ms", "state_from", "state_to", "metadata", "error"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        return json.dumps(payload, default=str, separators=(",", ":"), sort_keys=True)


def configure_logging(settings: Settings) -> logging.Logger:
    """Configure and return the application logger using the supplied settings."""
    destination = settings.log_destination
    destination.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    reset_logging(logger)
    logger.setLevel(settings.log_level)
    logger.propagate = False

    handler = logging.FileHandler(destination, encoding="utf-8")
    handler.setFormatter(JsonLinesFormatter())
    logger.addHandler(handler)
    return logger


def reset_logging(logger: logging.Logger | None = None) -> None:
    """Remove and close application-owned handlers, primarily for clean shutdown/tests."""
    active_logger = logger or logging.getLogger(LOGGER_NAME)
    for handler in active_logger.handlers[:]:
        active_logger.removeHandler(handler)
        handler.close()


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    game_id: str | None = None,
    duration_ms: float | None = None,
    state_from: str | None = None,
    state_to: str | None = None,
    metadata: Mapping[str, object] | None = None,
    error: BaseException | None = None,
) -> None:
    """Write a structured application event without exposing a traceback to users."""
    extra: dict[str, object] = {"event": event}
    if game_id is not None:
        extra["game_id"] = game_id
    if duration_ms is not None:
        extra["duration_ms"] = round(duration_ms, 3)
    if state_from is not None:
        extra["state_from"] = state_from
    if state_to is not None:
        extra["state_to"] = state_to
    if metadata is not None:
        extra["metadata"] = dict(metadata)
    if error is not None:
        extra["error"] = {"type": type(error).__name__, "message": str(error)}

    logger.log(level, event, extra=extra)


def log_state_transition(
    logger: logging.Logger,
    *,
    game_id: str,
    state_from: str,
    state_to: str,
) -> None:
    """Record a state-machine transition with the standard event shape."""
    log_event(
        logger,
        logging.INFO,
        "state_transition",
        game_id=game_id,
        state_from=state_from,
        state_to=state_to,
    )


@contextmanager
def timed_event(
    logger: logging.Logger,
    event: str,
    *,
    game_id: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> Iterator[None]:
    """Measure an operation and record either its success or safe failure details."""
    started_at = perf_counter()
    try:
        yield
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            event,
            game_id=game_id,
            duration_ms=(perf_counter() - started_at) * 1_000,
            metadata=metadata,
            error=exc,
        )
        raise
    else:
        log_event(
            logger,
            logging.INFO,
            event,
            game_id=game_id,
            duration_ms=(perf_counter() - started_at) * 1_000,
            metadata=metadata,
        )
