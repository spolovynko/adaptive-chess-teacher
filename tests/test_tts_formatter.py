"""Tests for deterministic announcements from canonical engine SAN."""

import chess
import pytest

from voicechess.tts import TtsAnnouncementError, TtsError, format_engine_move


@pytest.mark.parametrize(
    ("san", "text"),
    [
        ("Nf6", "Black plays knight f6."),
        ("Bc5", "Black plays bishop c5."),
        ("Rd8", "Black plays rook d8."),
        ("Qh4", "Black plays queen h4."),
        ("Kf7", "Black plays king f7."),
        ("e5", "Black plays pawn to e5."),
        ("Nxe4", "Black plays knight captures on e4."),
        ("Bxe5", "Black plays bishop captures on e5."),
        ("Rxd8", "Black plays rook captures on d8."),
        ("Qxh4", "Black plays queen captures on h4."),
        ("Kxf7", "Black plays king captures on f7."),
        ("exd4", "Black's pawn from e captures on d4."),
        ("Qh4+", "Black plays queen h4. Check."),
        ("Qh4#", "Black plays queen h4. Checkmate."),
        ("Bxe5+", "Black plays bishop captures on e5. Check."),
        ("Nxd3#", "Black plays knight captures on d3. Checkmate."),
        ("e5+", "Black plays pawn to e5. Check."),
        ("exd4#", "Black's pawn from e captures on d4. Checkmate."),
        ("O-O", "Black castles kingside."),
        ("O-O-O", "Black castles queenside."),
        ("O-O+", "Black castles kingside. Check."),
        ("O-O-O#", "Black castles queenside. Checkmate."),
        ("Nbd7", "Black plays knight from b to d7."),
        ("R8d7", "Black plays rook from 8 to d7."),
        ("Nb8d7", "Black plays knight from b8 to d7."),
        ("Nbxd7+", "Black plays knight from b captures on d7. Check."),
        ("R8xd7#", "Black plays rook from 8 captures on d7. Checkmate."),
        ("Nb8xd7", "Black plays knight from b8 captures on d7."),
    ],
)
def test_move_announcement_wording(san: str, text: str) -> None:
    assert format_engine_move(san) == text


@pytest.mark.parametrize(
    ("piece", "name"), [("Q", "queen"), ("R", "rook"), ("B", "bishop"), ("N", "knight")]
)
@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize(("suffix", "ending"), [("", ""), ("+", " Check."), ("#", " Checkmate.")])
def test_all_promotion_pieces_with_captures_and_endings(
    piece: str, name: str, capture: bool, suffix: str, ending: str
) -> None:
    san = f"{'dxe1' if capture else 'e1'}={piece}{suffix}"
    move = "Black's pawn from d captures on e1" if capture else "Black plays pawn to e1"
    assert format_engine_move(san) == f"{move} and promotes to {name}.{ending}"


@pytest.mark.parametrize(
    "san",
    [
        "",
        " ",
        " Nf6",
        "Nf6 ",
        "Nf6\n",
        "knight f6",
        "nf6",
        "P e5",
        "Pe5",
        "Ni6",
        "Nf9",
        "Nf0",
        "Nf6++",
        "Nf6+#",
        "Nf6!",
        "--",
        "0000",
        "e7e5",
        "0-O",
        "0-0",
        "O-O-O-O",
        "e1",
        "e8",
        "e5=Q",
        "e1=K",
        "e1=P",
        "e1=q",
        "e1Q",
        "Ne1=Q",
        "dxe1",
        "xe4",
        "Kef7",
        "K8f7",
        "e5; quit",
        "x" * 10_000,
    ],
)
def test_unsupported_notation_raises_a_safe_controlled_error(san: str) -> None:
    with pytest.raises(TtsAnnouncementError) as caught:
        format_engine_move(san)

    assert isinstance(caught.value, TtsError)
    assert str(caught.value) == "The engine move could not be converted into speech text."


@pytest.mark.parametrize(
    ("fen", "uci", "text"),
    [
        (
            "r3k2r/8/8/8/8/8/8/4K3 b kq - 0 1",
            "e8g8",
            "Black castles kingside.",
        ),
        (
            "r3k2r/8/8/8/8/8/8/4K3 b kq - 0 1",
            "e8c8",
            "Black castles queenside.",
        ),
        (
            "k7/8/8/8/3pP3/8/8/K7 b - e3 0 1",
            "d4e3",
            "Black's pawn from d captures on e3.",
        ),
        (
            "k7/8/8/8/8/8/4p3/K7 b - - 0 1",
            "e2e1q",
            "Black plays pawn to e1 and promotes to queen. Check.",
        ),
    ],
)
def test_special_moves_from_python_chess(fen: str, uci: str, text: str) -> None:
    board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    assert board.is_valid()
    assert move in board.legal_moves
    assert format_engine_move(board.san(move)) == text
    assert board.fen() == fen
    assert board.move_stack == []


def test_checkmate_from_a_real_game_sequence() -> None:
    board = chess.Board()
    for san in ["f3", "e5", "g4"]:
        board.push_san(san)

    move = board.parse_san("Qh4#")
    assert format_engine_move(board.san(move)) == "Black plays queen h4. Checkmate."
    board.push(move)
    assert board.is_checkmate()
