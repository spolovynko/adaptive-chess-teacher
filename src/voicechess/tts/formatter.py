"""Deterministic spoken text for canonical standard-chess SAN."""

import re

from voicechess.tts.errors import TtsAnnouncementError

_PIECE_NAMES = {"K": "king", "Q": "queen", "R": "rook", "B": "bishop", "N": "knight"}
_SAN = re.compile(
    r"(?:"
    r"(?P<castle>O-O(?:-O)?)"
    r"|(?P<piece>[KQRBN])(?P<source>[a-h][1-8]?|[1-8])?"
    r"(?P<piece_capture>x)?(?P<piece_target>[a-h][1-8])"
    r"|(?:(?P<pawn_source>[a-h])x)?(?P<pawn_target>[a-h][2-7])"
    r"|(?:(?P<promotion_source>[a-h])x)?(?P<promotion_target>[a-h][18])"
    r"=(?P<promotion>[QRBN])"
    r")(?P<ending>[+#])?"
)


def format_engine_move(san: str) -> str:
    """Render canonical SAN as a Black-move announcement.

    The caller must supply SAN already validated by python-chess. This checks the
    supported notation shape, not move legality, canonicality, or check accuracy in
    a position. En passant uses the ordinary pawn-capture form of canonical SAN.
    """
    match = _SAN.fullmatch(san)
    if match is None:
        raise TtsAnnouncementError

    if castle := match["castle"]:
        side = "kingside" if castle == "O-O" else "queenside"
        phrase = f"Black castles {side}"
    elif piece := match["piece"]:
        source = match["source"]
        if piece == "K" and source is not None:
            raise TtsAnnouncementError
        origin = f" from {source}" if source else ""
        action = " captures on" if match["piece_capture"] else " to" if source else ""
        phrase = f"Black plays {_PIECE_NAMES[piece]}{origin}{action} {match['piece_target']}"
    else:
        source = match["pawn_source"] or match["promotion_source"]
        target = match["pawn_target"] or match["promotion_target"]
        if source:
            phrase = f"Black's pawn from {source} captures on {target}"
        else:
            phrase = f"Black plays pawn to {target}"
        if promotion := match["promotion"]:
            phrase += f" and promotes to {_PIECE_NAMES[promotion]}"

    ending = {"+": " Check.", "#": " Checkmate."}.get(match["ending"], "")
    return f"{phrase}.{ending}"
