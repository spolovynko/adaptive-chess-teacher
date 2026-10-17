"""Exceptions raised for invalid game-domain actions."""

from __future__ import annotations


class GameError(Exception):
    """Base exception for controlled game-domain failures."""


class GameNotActiveError(GameError):
    """Raised when an action requires an active game."""

    def __init__(self) -> None:
        super().__init__("This game is no longer active. Start a new game to continue.")


class MoveInputError(GameError):
    """Base exception for a rejected player move submission."""


class EmptySanError(MoveInputError):
    """Raised when the player submits no SAN move text."""

    def __init__(self) -> None:
        super().__init__("Enter a move in Standard Algebraic Notation, for example e4 or Nf3.")


class InvalidSanError(MoveInputError):
    """Raised when move text cannot be parsed as Standard Algebraic Notation."""

    def __init__(self, san: str) -> None:
        self.san = san
        super().__init__(f"'{san}' is not valid Standard Algebraic Notation.")


class IllegalSanMoveError(MoveInputError):
    """Raised when valid-looking SAN cannot be played in the current position."""

    def __init__(self, san: str) -> None:
        self.san = san
        super().__init__(f"'{san}' is not a legal move in the current position.")


class IllegalEngineMoveError(GameError):
    """Raised when the engine boundary supplies an illegal move."""

    def __init__(self) -> None:
        super().__init__("The engine returned an illegal move.")
