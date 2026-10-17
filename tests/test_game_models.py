"""Tests for game-domain value types."""

from voicechess.game import GameResult, GameStatus, PlayerColor


def test_player_colors_are_wire_friendly_and_have_opponents() -> None:
    assert PlayerColor.WHITE.value == "white"
    assert PlayerColor.BLACK.value == "black"
    assert PlayerColor.WHITE.opponent is PlayerColor.BLACK
    assert PlayerColor.BLACK.opponent is PlayerColor.WHITE


def test_game_status_values_cover_phase_zero_terminal_conditions() -> None:
    assert {status.value for status in GameStatus} == {
        "active",
        "checkmate",
        "stalemate",
        "draw",
        "resigned",
    }


def test_game_results_use_standard_pgn_notation() -> None:
    assert GameResult.WHITE_WIN.value == "1-0"
    assert GameResult.BLACK_WIN.value == "0-1"
    assert GameResult.DRAW.value == "1/2-1/2"
