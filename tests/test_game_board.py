"""Tests for browser-safe board representation."""

import chess

from voicechess.game.board import piece_map


def test_initial_piece_map_uses_algebraic_squares_and_case_for_color() -> None:
    board = piece_map(chess.Board())

    assert len(board) == 32
    assert board["a1"] == "R"
    assert board["e1"] == "K"
    assert board["a8"] == "r"
    assert board["e8"] == "k"
    assert "e4" not in board


def test_piece_map_reflects_moves_without_mutating_board() -> None:
    chess_board = chess.Board()
    chess_board.push_san("e4")

    board = piece_map(chess_board)

    assert board["e4"] == "P"
    assert "e2" not in board
    assert chess_board.peek() == chess.Move.from_uci("e2e4")
