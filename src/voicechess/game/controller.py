"""Game orchestration built on python-chess and the lifecycle state machine."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from time import perf_counter
from uuid import UUID, uuid4

import chess

from voicechess.game.board import piece_map
from voicechess.game.errors import (
    EmptySanError,
    EngineMoveNotExpectedError,
    GameNotActiveError,
    IllegalEngineMoveError,
    IllegalSanMoveError,
    InvalidSanError,
    PlayerMoveNotExpectedError,
)
from voicechess.game.models import GameResult, GameStatus, PlayerColor
from voicechess.game.outcome import automatic_outcome
from voicechess.game.snapshot import GameSnapshot
from voicechess.logging import log_event, timed_event
from voicechess.state import GameState, GameStateMachine


class GameController:
    """Own the mutable rules state for one standard chess game."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        game_id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._logger = logger
        self._game_id_factory = game_id_factory
        self._player_color = PlayerColor.WHITE
        self._initialize_game()

    def _initialize_game(self) -> None:
        """Create a fresh standard game with a new identity."""
        self._game_id = str(self._game_id_factory())
        self._board = chess.Board()
        self._moves: list[str] = []
        self._status = GameStatus.ACTIVE
        self._result: GameResult | None = None
        self._last_move: str | None = None
        self._message = "White to move."
        self._state_machine = GameStateMachine(game_id=self._game_id, logger=self._logger)

        log_event(
            self._logger,
            logging.INFO,
            "game_created",
            game_id=self._game_id,
            metadata={"player_color": self._player_color.value},
        )
        self._state_machine.start()

    @property
    def game_id(self) -> str:
        """Return this game's stable UUID string."""
        return self._game_id

    @property
    def player_color(self) -> PlayerColor:
        """Return the colour controlled by the human player."""
        return self._player_color

    @property
    def fen(self) -> str:
        """Return the current position in Forsyth-Edwards Notation."""
        return self._board.fen()

    @property
    def side_to_move(self) -> PlayerColor:
        """Return the colour whose turn it is."""
        if self._board.turn == chess.WHITE:
            return PlayerColor.WHITE
        return PlayerColor.BLACK

    @property
    def moves(self) -> Sequence[str]:
        """Return an immutable copy of canonical SAN move history."""
        return tuple(self._moves)

    @property
    def status(self) -> GameStatus:
        """Return the user-visible game status."""
        return self._status

    @property
    def result(self) -> GameResult | None:
        """Return the final result, or None while the game remains active."""
        return self._result

    @property
    def last_move(self) -> str | None:
        """Return the last move in canonical SAN, if one has been played."""
        return self._last_move

    @property
    def message(self) -> str:
        """Return the current user-facing game message."""
        return self._message

    @property
    def state(self) -> GameState:
        """Return the current lifecycle state."""
        return self._state_machine.state

    def submit_player_san(self, san: str) -> str:
        """Validate and apply one player move in Standard Algebraic Notation."""
        self._ensure_active("player_move")
        error: Exception
        if self.state is not GameState.PLAYER_INPUT or self.side_to_move is not self.player_color:
            error = PlayerMoveNotExpectedError()
            self._log_rejected_action("player_move_rejected", error)
            raise error

        normalized_san = san.strip()
        if not normalized_san:
            error = EmptySanError()
            self._log_rejected_action("player_move_rejected", error)
            raise error

        self._state_machine.transition_to(GameState.RESOLVING)
        started_at = perf_counter()
        try:
            move = self._board.parse_san(normalized_san)
        except chess.IllegalMoveError as exc:
            error = IllegalSanMoveError(normalized_san)
            self._recover_rejected_san(error, started_at)
            raise error from exc
        except chess.InvalidMoveError as exc:
            error = InvalidSanError(normalized_san)
            self._recover_rejected_san(error, started_at)
            raise error from exc

        log_event(
            self._logger,
            logging.INFO,
            "san_resolved",
            game_id=self.game_id,
            duration_ms=(perf_counter() - started_at) * 1_000,
            metadata={"san": normalized_san},
        )
        self._state_machine.transition_to(GameState.APPLYING_PLAYER_MOVE)
        canonical_san = self._apply_move(move, event="player_move_applied")

        if not self._finish_if_game_over():
            self._message = "Black is thinking."
            self._state_machine.transition_to(GameState.ENGINE_TURN)
        return canonical_san

    def apply_engine_move(self, move: chess.Move) -> str:
        """Validate and apply a move supplied by the future Stockfish boundary."""
        self._ensure_active("engine_move")
        error: Exception
        if self.state is not GameState.ENGINE_TURN or self.side_to_move is self.player_color:
            error = EngineMoveNotExpectedError()
            self._log_rejected_action("engine_move_rejected", error)
            raise error

        if move not in self._board.legal_moves:
            error = IllegalEngineMoveError(move.uci())
            self._log_rejected_action(
                "engine_move_rejected",
                error,
                metadata={"uci": move.uci()},
            )
            raise error

        self._state_machine.transition_to(GameState.APPLYING_ENGINE_MOVE)
        canonical_san = self._apply_move(move, event="engine_move_applied")

        if not self._finish_if_game_over():
            self._message = "White to move."
            self._state_machine.transition_to(GameState.RETURNING_SNAPSHOT)
            self._state_machine.transition_to(GameState.PLAYER_INPUT)
        return canonical_san

    def recover_from_engine_failure(self) -> None:
        """Roll back the pending player move after an engine request fails."""
        self._ensure_active("engine_failure_recovery")
        if self.state is not GameState.ENGINE_TURN or self.side_to_move is self.player_color:
            error = EngineMoveNotExpectedError()
            self._log_rejected_action("engine_recovery_rejected", error)
            raise error

        rolled_back_san = self._moves.pop()
        self._board.pop()
        self._last_move = self._moves[-1] if self._moves else None
        self._message = "White to move. Please try again."
        self._state_machine.transition_to(GameState.PLAYER_INPUT)
        log_event(
            self._logger,
            logging.WARNING,
            "engine_turn_recovered",
            game_id=self.game_id,
            metadata={"rolled_back_san": rolled_back_san},
        )

    def resign(self) -> None:
        """End the active game as a player resignation."""
        self._ensure_active("resign")
        self._status = GameStatus.RESIGNED
        self._result = GameResult.BLACK_WIN
        self._message = "White resigned. Black wins."
        self._state_machine.mark_game_over()
        log_event(
            self._logger,
            logging.INFO,
            "game_resigned",
            game_id=self.game_id,
            metadata={"player_color": self.player_color.value},
        )

    def new_game(self) -> GameSnapshot:
        """Replace the current game with a fresh board and UUID."""
        previous_game_id = self.game_id
        if self.state is not GameState.GAME_OVER:
            self._state_machine.mark_game_over()
        log_event(
            self._logger,
            logging.INFO,
            "game_replaced",
            game_id=previous_game_id,
        )
        self._initialize_game()
        return self.snapshot()

    def snapshot(self) -> GameSnapshot:
        """Build an immutable representation of the current game."""
        with timed_event(self._logger, "snapshot_built", game_id=self.game_id):
            return GameSnapshot(
                game_id=self.game_id,
                fen=self.fen,
                side_to_move=self.side_to_move,
                board=piece_map(self._board),
                moves=self.moves,
                status=self.status,
                result=self.result,
                last_move=self.last_move,
                message=self.message,
                state=self.state,
            )

    def _apply_move(self, move: chess.Move, *, event: str) -> str:
        canonical_san = self._board.san(move)
        with timed_event(
            self._logger,
            event,
            game_id=self.game_id,
            metadata={"san": canonical_san, "uci": move.uci()},
        ):
            self._board.push(move)
            self._moves.append(canonical_san)
            self._last_move = canonical_san
        return canonical_san

    def _finish_if_game_over(self) -> bool:
        outcome = automatic_outcome(self._board)
        if outcome is None:
            return False

        self._status = outcome.status
        self._result = outcome.result
        self._message = outcome.message
        self._state_machine.mark_game_over()
        log_event(
            self._logger,
            logging.INFO,
            "game_over",
            game_id=self.game_id,
            metadata={"status": self.status.value, "result": outcome.result.value},
        )
        return True

    def _recover_rejected_san(self, error: Exception, started_at: float) -> None:
        self._state_machine.transition_to(GameState.PLAYER_INPUT)
        self._log_rejected_action(
            "player_move_rejected",
            error,
            duration_ms=(perf_counter() - started_at) * 1_000,
        )

    def _ensure_active(self, action: str) -> None:
        if self.status is GameStatus.ACTIVE:
            return
        error = GameNotActiveError()
        self._log_rejected_action(
            "game_action_rejected",
            error,
            metadata={"action": action, "status": self.status.value},
        )
        raise error

    def _log_rejected_action(
        self,
        event: str,
        error: Exception,
        *,
        duration_ms: float | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        log_event(
            self._logger,
            logging.WARNING,
            event,
            game_id=self.game_id,
            duration_ms=duration_ms,
            metadata=metadata,
            error=error,
        )
