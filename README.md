# Adaptive Chess Teacher

Phase 0 builds a fully local browser chess game against Stockfish. The player enters
Standard Algebraic Notation (SAN), such as `e4`, `Nf3`, or `O-O`; later phases add
voice and coaching capabilities.

## Prerequisites

- Windows, macOS, or Linux with Python 3.12.
- A local [Stockfish](https://stockfishchess.org/download/) executable.

## Setup

This project uses [uv](https://docs.astral.sh/uv/) to resolve dependencies, create the
local virtual environment, and maintain the committed `uv.lock` file. Follow the
[official installation instructions](https://docs.astral.sh/uv/getting-started/installation/)
for your platform. On Windows, Winget can install it directly:

```powershell
winget install --id Astral.uv -e
```

From the repository root, create or exactly synchronize the project environment:

```powershell
uv sync
```

`uv sync` creates `.venv` when necessary and installs the application plus local
development tools from `pyproject.toml` and `uv.lock`. Do not use ad-hoc `pip install`
commands for project dependencies.

Verify the scaffold:

```powershell
uv run python -m voicechess --help
```

Start the local application with:

```powershell
uv run voicechess
```

Then open `http://127.0.0.1:8000` in a browser. The page and its assets are served
locally and make no runtime requests outside the application. If Stockfish is missing,
the page still opens and reports that the engine is unavailable; moves require a valid
`VOICECHESS_STOCKFISH_PATH` or a `stockfish` executable on `PATH`.

## Development checks

Run these checks before committing a change:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
git diff --check
```

To apply safe Ruff formatting changes, use `uv run ruff format .`. The committed
`uv.lock` file must be updated whenever dependencies change.

## Configuration

All configuration has a local default and can be overridden with an environment
variable prefixed by `VOICECHESS_`. Store local overrides in an untracked `.env` file
or set them in the shell before starting the application.

| Setting | Environment variable | Default |
| --- | --- | --- |
| Application host | `VOICECHESS_APP_HOST` | `127.0.0.1` |
| Application port | `VOICECHESS_APP_PORT` | `8000` |
| Stockfish executable | `VOICECHESS_STOCKFISH_PATH` | `stockfish` |
| Stockfish skill, 0–20 | `VOICECHESS_STOCKFISH_SKILL_LEVEL` | `5` |
| Engine search depth | `VOICECHESS_ENGINE_SEARCH_DEPTH` | `8` |
| Engine time limit, milliseconds | `VOICECHESS_ENGINE_MOVE_TIME_MS` | unset |
| Engine start timeout, milliseconds | `VOICECHESS_ENGINE_STARTUP_TIMEOUT_MS` | `5000` |
| Engine move timeout, milliseconds | `VOICECHESS_ENGINE_MOVE_TIMEOUT_MS` | `10000` |
| PGN export directory | `VOICECHESS_PGN_EXPORT_DIR` | `exports` |
| Log level | `VOICECHESS_LOG_LEVEL` | `INFO` |
| Log file | `VOICECHESS_LOG_DESTINATION` | `logs/voicechess.jsonl` |

Application logs use JSON Lines (`.jsonl`): one structured, append-only JSON event
per line. This preserves queryable fields such as timestamps, log level, event name,
game ID, state transitions, latency, and safe error details without making log writes
depend on a single valid JSON document.

Every accepted game-lifecycle change is recorded as an `INFO` `state_transition` event.
Rejected transitions are recorded as `WARNING` `state_transition_rejected` events and
leave the current state unchanged.

For example, set an explicit Stockfish location and a gentler engine strength on
Windows:

```powershell
$env:VOICECHESS_STOCKFISH_PATH = "C:\Tools\stockfish\stockfish.exe"
$env:VOICECHESS_STOCKFISH_SKILL_LEVEL = "3"
```

The search depth and move-time settings control how long Stockfish should think under
normal conditions. The move timeout is a separate hard failure deadline for an
unresponsive engine. When a move-time limit is configured, it must be shorter than the
move timeout. A timeout or engine protocol failure closes that process so a stuck or
invalid engine cannot affect later turns; the application can then start a fresh
process.

Reserved, currently unused settings are available for future phases:
`VOICECHESS_WHISPER_MODEL_NAME`, `VOICECHESS_PIPER_VOICE_NAME`,
`VOICECHESS_LOCAL_LLM_MODEL_NAME`, and the three `VOICECHESS_COACHING_*_THRESHOLD_CP`
values.

## Phase 0 game rules

The player controls White and Stockfish controls Black. Checkmate, stalemate,
insufficient material, the seventy-five-move rule, and fivefold repetition end the
game automatically. Claimable draws, such as threefold repetition and the fifty-move
rule, are not claimed automatically because Phase 0 does not expose a draw-claim action.

### Board snapshot contract

Game snapshots represent the board as a JSON-compatible mapping of occupied algebraic
squares to standard single-character piece symbols. White pieces use uppercase symbols
(`P`, `N`, `B`, `R`, `Q`, `K`), Black pieces use lowercase symbols, and empty squares
are omitted. For example, after `e4`, the mapping contains `"e4": "P"` and no `"e2"`
entry. This keeps chess rules in the backend while giving the browser a small, stable
rendering contract.

### PGN export contract

PGN exports are reconstructed from canonical SAN history and checked against the
snapshot's final FEN. Generated documents include standard event, site, date, player,
and result headers and are parsed back with `python-chess` before they are written.
Each game uses `game-<game-id>.pgn` in the configured export directory. Re-exporting
the same game atomically replaces its previous file so a failed write cannot leave a
partial PGN at the final path.

The API schemas expose the export filename and PGN content to the browser but never
expose the server's local filesystem path. Other schemas define strict contracts for
SAN requests, game snapshots, health status, and controlled error responses. API
routes using these schemas are added in Phase 0 Step 10.

## Phase 0 boundaries

- Fully local FastAPI browser application.
- `python-chess` owns rules, legal moves, board state, SAN, and PGN.
- Stockfish supplies the opponent move.
- No voice input, speech output, coaching, LLM, click-to-move, multiplayer, or cloud
  services are included in Phase 0.

