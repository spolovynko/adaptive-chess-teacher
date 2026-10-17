"""Controlled failures raised while constructing or writing PGN exports."""

from __future__ import annotations


class PgnExportError(RuntimeError):
    """Base exception for failures while exporting a game."""


class InvalidGameHistoryError(PgnExportError):
    """Raised when stored SAN history cannot reconstruct the recorded game."""

    def __init__(self, ply: int, san: str) -> None:
        self.ply = ply
        self.san = san
        super().__init__(f"Cannot reconstruct move {ply} from SAN '{san}'.")


class InconsistentGameSnapshotError(PgnExportError):
    """Raised when reconstructed history does not produce the snapshot position."""

    def __init__(self) -> None:
        super().__init__("The game history does not match the current position.")


class InvalidPgnError(PgnExportError):
    """Raised when generated PGN cannot be parsed back into the same game."""

    def __init__(self) -> None:
        super().__init__("The generated PGN could not be validated.")


class PgnWriteError(PgnExportError):
    """Raised when a valid PGN document cannot be written to disk."""

    def __init__(self) -> None:
        super().__init__("The PGN file could not be written.")
