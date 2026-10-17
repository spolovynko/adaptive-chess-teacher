"""Tests for browser-safe board representation."""

import json

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
    original_fen = chess_board.fen()

    board = piece_map(chess_board)

    assert board["e4"] == "P"
    assert "e2" not in board
    assert chess_board.fen() == original_fen
    assert chess_board.peek() == chess.Move.from_uci("e2e4")


def test_empty_board_produces_empty_piece_map() -> None:
    assert piece_map(chess.Board.empty()) == {}


def test_piece_map_removes_a_captured_piece() -> None:
    chess_board = chess.Board()
    chess_board.push_san("e4")
    chess_board.push_san("d5")
    chess_board.push_san("exd5")

    board = piece_map(chess_board)

    assert len(board) == 31
    assert board["d5"] == "P"
    assert "e4" not in board


def test_piece_map_reflects_castling() -> None:
    chess_board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    chess_board.push_san("O-O")

    board = piece_map(chess_board)

    assert board["g1"] == "K"
    assert board["f1"] == "R"
    assert "e1" not in board
    assert "h1" not in board


def test_piece_map_uses_promoted_piece_symbol() -> None:
    chess_board = chess.Board("8/P7/8/8/8/8/4k3/7K w - - 0 1")
    chess_board.push_san("a8=Q")

    board = piece_map(chess_board)

    assert board["a8"] == "Q"
    assert "a7" not in board


def test_piece_map_reflects_en_passant_capture() -> None:
    chess_board = chess.Board()
    for san in ("e4", "a6", "e5", "d5", "exd6"):
        chess_board.push_san(san)

    board = piece_map(chess_board)

    assert board["d6"] == "P"
    assert "d5" not in board
    assert "e5" not in board


def test_piece_map_is_directly_json_serializable() -> None:
    board = piece_map(chess.Board())

    encoded = json.dumps(board)

    assert json.loads(encoded) == board
