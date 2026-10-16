# Adaptive Chess Teacher

Phase 0 builds a fully local browser chess game against Stockfish. The player enters
Standard Algebraic Notation (SAN), such as `e4`, `Nf3`, or `O-O`; later phases add
voice and coaching capabilities.

## Prerequisites

- Windows, macOS, or Linux with Python 3.12.
- A local [Stockfish](https://stockfishchess.org/download/) executable. Its path will
  be configured in Phase 0 Step 2.

## Setup

From the repository root, create and activate a virtual environment, then install the
application and its development tools:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The eventual local start command is:

```powershell
voicechess
```

It will serve the browser application at `http://127.0.0.1:8000`. This command is
already registered but will become operational after the FastAPI application is added
in Phase 0 Step 10. At the end of the current foundation step, verify installation
with:

```powershell
python -m voicechess --help
```

## Phase 0 boundaries

- Fully local FastAPI browser application.
- `python-chess` owns rules, legal moves, board state, SAN, and PGN.
- Stockfish supplies the opponent move.
- No voice input, speech output, coaching, LLM, click-to-move, multiplayer, or cloud
  services are included in Phase 0.

