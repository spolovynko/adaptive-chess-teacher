"""Game lifecycle states and validated transitions."""

from __future__ import annotations

import logging
from enum import Enum

from voicechess.logging import log_event, log_state_transition


class GameState(str, Enum):
    """The lifecycle stages of one chess game request."""

    IDLE = "IDLE"
    PLAYER_INPUT = "PLAYER_INPUT"
    RESOLVING = "RESOLVING"
    APPLYING_PLAYER_MOVE = "APPLYING_PLAYER_MOVE"
    ENGINE_TURN = "ENGINE_TURN"
    APPLYING_ENGINE_MOVE = "APPLYING_ENGINE_MOVE"
    RETURNING_SNAPSHOT = "RETURNING_SNAPSHOT"
    GAME_OVER = "GAME_OVER"


ALLOWED_TRANSITIONS: dict[GameState, frozenset[GameState]] = {
    GameState.IDLE: frozenset({GameState.PLAYER_INPUT, GameState.GAME_OVER}),
    GameState.PLAYER_INPUT: frozenset({GameState.RESOLVING, GameState.GAME_OVER}),
    GameState.RESOLVING: frozenset({GameState.APPLYING_PLAYER_MOVE, GameState.GAME_OVER}),
    GameState.APPLYING_PLAYER_MOVE: frozenset({GameState.ENGINE_TURN, GameState.GAME_OVER}),
    GameState.ENGINE_TURN: frozenset({GameState.APPLYING_ENGINE_MOVE, GameState.GAME_OVER}),
    GameState.APPLYING_ENGINE_MOVE: frozenset({GameState.RETURNING_SNAPSHOT, GameState.GAME_OVER}),
    GameState.RETURNING_SNAPSHOT: frozenset({GameState.PLAYER_INPUT, GameState.GAME_OVER}),
    GameState.GAME_OVER: frozenset({GameState.IDLE}),
}


class InvalidStateTransition(ValueError):
    """Raised when code requests a lifecycle change outside the allowed state graph."""

    def __init__(self, state_from: GameState, state_to: GameState) -> None:
        self.state_from = state_from
        self.state_to = state_to
        super().__init__(f"Cannot transition from {state_from.value} to {state_to.value}.")


class GameStateMachine:
    """Track and validate one game's lifecycle independently of chess rules or transport."""

    def __init__(self, game_id: str, logger: logging.Logger) -> None:
        self.game_id = game_id
        self._logger = logger
        self._state = GameState.IDLE

    @property
    def state(self) -> GameState:
        """Return the current stage."""
        return self._state

    def can_transition_to(self, next_state: GameState) -> bool:
        """Return whether a requested stage is valid from the current stage."""
        return next_state in ALLOWED_TRANSITIONS[self._state]

    def transition_to(self, next_state: GameState) -> GameState:
        """Apply one valid state transition and record it as an INFO event."""
        state_from = self._state
        if not self.can_transition_to(next_state):
            error = InvalidStateTransition(state_from, next_state)
            log_event(
                self._logger,
                logging.WARNING,
                "state_transition_rejected",
                game_id=self.game_id,
                state_from=state_from.value,
                state_to=next_state.value,
                error=error,
            )
            raise error

        self._state = next_state
        log_state_transition(
            self._logger,
            game_id=self.game_id,
            state_from=state_from.value,
            state_to=next_state.value,
        )
        return self._state

    def start(self) -> GameState:
        """Move a newly created machine from IDLE to player input."""
        return self.transition_to(GameState.PLAYER_INPUT)

    def mark_game_over(self) -> GameState:
        """End the active or interrupted game from any lifecycle stage."""
        return self.transition_to(GameState.GAME_OVER)

    def reset(self) -> GameState:
        """Return an ended or interrupted game to the player-input state."""
        if self._state is not GameState.GAME_OVER:
            self.mark_game_over()
        self.transition_to(GameState.IDLE)
        return self.start()
