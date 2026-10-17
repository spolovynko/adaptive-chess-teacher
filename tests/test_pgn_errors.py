"""Tests for controlled PGN export errors."""

import pytest

from voicechess.pgn import (
    InconsistentGameSnapshotError,
    InvalidGameHistoryError,
    InvalidPgnError,
    PgnWriteError,
)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            InvalidGameHistoryError(3, "bad"),
            "Cannot reconstruct move 3 from SAN 'bad'.",
        ),
        (
            InconsistentGameSnapshotError(),
            "The game history does not match the current position.",
        ),
        (InvalidPgnError(), "The generated PGN could not be validated."),
        (PgnWriteError(), "The PGN file could not be written."),
    ],
)
def test_pgn_errors_have_stable_messages(error: Exception, message: str) -> None:
    assert str(error) == message
