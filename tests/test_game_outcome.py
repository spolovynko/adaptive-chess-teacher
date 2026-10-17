"""Tests for automatic game-ending rule translation."""

import chess

from voicechess.game import GameResult, GameStatus
from voicechess.game.outcome import automatic_outcome


def test_checkmate_outcome_identifies_winner() -> None:
    board = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")

    outcome = automatic_outcome(board)

    assert outcome is not None
    assert outcome.status is GameStatus.CHECKMATE
    assert outcome.result is GameResult.BLACK_WIN
    assert outcome.message == "Black wins by checkmate."


def test_stalemate_is_reported_separately_from_other_draws() -> None:
    board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")

    outcome = automatic_outcome(board)

    assert outcome is not None
    assert outcome.status is GameStatus.STALEMATE
    assert outcome.result is GameResult.DRAW
    assert outcome.message == "Draw by stalemate."


def test_insufficient_material_is_an_automatic_draw() -> None:
    board = chess.Board("8/8/8/8/8/8/8/K6k w - - 0 1")

    outcome = automatic_outcome(board)

    assert outcome is not None
    assert outcome.status is GameStatus.DRAW
    assert outcome.result is GameResult.DRAW
    assert outcome.message == "Draw by insufficient material."


def test_seventy_five_move_rule_is_an_automatic_draw() -> None:
    board = chess.Board("7k/8/8/8/8/8/R7/K7 w - - 150 1")

    outcome = automatic_outcome(board)

    assert outcome is not None
    assert outcome.status is GameStatus.DRAW
    assert outcome.result is GameResult.DRAW
    assert outcome.message == "Draw by the seventy-five-move rule."


def test_fivefold_repetition_is_automatic_but_threefold_is_not_claimed() -> None:
    board = chess.Board()
    cycle = ("g1f3", "g8f6", "f3g1", "f6g8")
    for _ in range(2):
        for uci in cycle:
            board.push_uci(uci)

    assert board.can_claim_threefold_repetition()
    assert automatic_outcome(board) is None

    for _ in range(2):
        for uci in cycle:
            board.push_uci(uci)

    outcome = automatic_outcome(board)
    assert outcome is not None
    assert outcome.status is GameStatus.DRAW
    assert outcome.message == "Draw by fivefold repetition."
