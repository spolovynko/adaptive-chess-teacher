# Voice Chess Coach — Build Spec

You are implementing a fully local, voice-controlled chess game with a coaching layer.
Read this entire document before writing code. Work in phases; do not skip ahead.

---

## 1. Goal

A desktop application the user plays by speaking. They say a move, the program confirms
it, plays it, replies with its own move, and comments on the quality of the move they
just made.

This is a learning project. Clarity and observability matter more than cleverness.
Prefer boring, readable code with explicit state over abstraction.

---

## 2. Hard constraints

- **Free and open source only.** No paid APIs, no hosted inference, no accounts.
- **Fully offline after first model download.** No network calls at runtime.
- **CPU-only must work.** GPU may be used if present but is never required.
- Python 3.12. Dependencies pinned in `pyproject.toml` and locked in `uv.lock`.
- Target latency: user finishes speaking → engine's reply spoken aloud in under 2 seconds.

---

## 3. Core design principle

Three different systems own three different things. Do not blur these boundaries.

| Concern | Owner | Never |
|---|---|---|
| Legality, board state, SAN/UCI, PGN | `python-chess` | Never hand-roll move generation |
| Position evaluation, best move, opponent play | Stockfish | Never let the LLM evaluate a position |
| Natural language in and out | Local LLM | Never let the LLM decide what is good or bad |

The LLM receives pre-computed facts and turns them into sentences. If the LLM is ever in
a position to *judge* a move or *generate* a move, the design is wrong.

---

## 4. Components

| Layer | Library | Notes |
|---|---|---|
| Audio I/O | `sounddevice` | 16 kHz mono int16 end to end, no resampling |
| VAD | `silero-vad` | Closes utterance after ~700 ms silence |
| Wake word | `openWakeWord` | Phase 5 only |
| STT | `faster-whisper` | `small.en`, int8 compute type |
| Fuzzy match | `rapidfuzz`, `jellyfish` | Edit distance + Metaphone |
| Rules | `python-chess` | |
| Engine | Stockfish 19 or compatible UCI release | Opponent now; analyst in Phase 4 |
| LLM | Ollama, `qwen2.5:7b-instruct-q4_K_M` | Fall back to 3b on ≤8 GB RAM |
| TTS | `piper-tts` | |

Orchestration is plain `asyncio` plus an explicit state machine. **Do not introduce an
agent framework** (LangChain, LangGraph, CrewAI, etc.). Control flow here is a fixed loop
with known transitions; a framework would hide the latency the project exists to expose.

---

## 5. State machine

The diagram below is the target voice interaction loop for later phases. Phase 0 uses
the browser game lifecycle documented in the implementation notes while preserving the
same explicit-state design.

```
IDLE → LISTENING → TRANSCRIBING → RESOLVING → CONFIRMING → APPLYING
                                      ↑            │
                                      └────────────┘  (user says "no")
APPLYING → ENGINE_TURN → SPEAKING → IDLE
```

Every transition logs a timestamped line. Latency per stage must be visible in the logs
from day one — this is a primary requirement, not debug scaffolding.

---

## 6. Move resolution

The central problem: spoken chess squares are highly confusable ("B4", "D4", "E4", "G4"
all sound alike through a microphone). Do not solve this with a larger Whisper model.

Algorithm, per turn:

1. Ask `python-chess` for all legal moves (typically 25–40). This is a tiny closed vocabulary.
2. Render each legal move into one or more spoken forms: `"Nf3"` → `["knight f3",
   "knight to f3", "knight takes f3", "night f3"]`.
3. Seed `faster-whisper`'s `initial_prompt` with these forms to bias decoding.
4. Score the transcript against every spoken form using a blend of `rapidfuzz` ratio and
   Metaphone phonetic distance.
5. If the top candidate's margin over the runner-up exceeds a threshold, accept it.
   Otherwise ask a disambiguating question: *"Bishop c4, or bishop e4?"*
6. **Always read the resolved move back and wait for confirmation before applying it.**

An illegal move is impossible by construction, because only legal moves are ever candidates.

Alongside moves, a keyword router handles commands — "take back", "new game", "resign",
"repeat that", "how am I doing". Commands are matched with plain string rules, **not** the LLM.

---

## 7. The coach

Runs after the user's move is applied, in a background thread, in parallel with Stockfish
choosing its reply.

### 7.1 Scoring

Analyse the position before and after the user's move (`multipv=3`, fixed depth ~14).
Convert centipawn scores to win percentage before comparing — raw centipawn loss is
misleading in won and lost positions.

```python
def win_pct(cp: int) -> float:
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)
```

Classify on the win-percentage delta from the mover's perspective:

| Delta | Label |
|---|---|
| < 2 | good |
| 2–5 | inaccuracy |
| 5–10 | mistake |
| > 10 | blunder |

Thresholds live in one config dict and are expected to be tuned by play.

### 7.2 Mate scores

Mate scores are not numbers and must bypass the arithmetic entirely. `python-chess`
returns `PovScore`; branch on `.is_mate()` and classify the transition as a category:
kept mate, threw away mate, walked into mate, escaped mate. Converting mate to a large
centipawn value produces false blunder reports and is explicitly forbidden.

### 7.3 Fact sheet

Build a JSON object and pass **only this** to the LLM:

```json
{
  "played": "Bc5",
  "best": "Nxe5",
  "pv": ["Nxe5", "Qd4", "f6"],
  "win_pct_delta": 7.4,
  "label": "mistake",
  "phase": "opening",
  "findings": ["hanging_piece: bishop on c5 attacked by b4, undefended"]
}
```

**Never pass a FEN or raw board state to the LLM.** Models cannot read a position from
notation reliably and will hallucinate pieces onto squares.

Start with findings empty — the principal variation alone explains most mistakes. Add
detectors only in response to observed failures (see Phase 4). The one detector to
implement up front is hanging-piece detection: after the move, scan the mover's pieces
for any attacked by a lower-valued piece with no defender.

### 7.4 Narrator

System prompt must instruct the model to narrate the supplied facts in at most two
sentences, and explicitly forbid: inventing variations, adding its own assessment of the
move, or naming squares not present in the fact sheet.

### 7.5 Gating and ordering

- Speak only on `inaccuracy` or worse, plus roughly one in five `good` moves so the
  coaching is not purely negative. Verbosity is configurable.
- **Speak the engine's reply first, commentary second.** Never block the move
  announcement on LLM generation.
- On `blunder`, offer a takeback before revealing the answer: *"That loses a piece —
  want to try again?"*

---

## 8. Phases

Implement one phase at a time. Each ends with a working program. **Stop after each phase
and report before starting the next.**

**Phase 0 — Local browser chess.** FastAPI + `python-chess` + Stockfish. The user sees
an accessible visual board, moves White's pieces by drag-and-drop or square selection,
receives an engine reply, and can start a new game, resign, or export validated PGN. A
Manual/Voice control exposes the planned interaction modes, but Voice is clearly marked
unavailable. No audio or coaching.
*Done when:* a full game is playable through the localhost browser interface, failures
do not corrupt state, structured timings are present, and exports round-trip as PGN.

**Phase 1 — Output voice.** Convert canonical engine SAN into spoken text and generate
audio locally through Piper. The player continues using manual board input.
*Done when:* every successful engine reply can be spoken, speech failure leaves a valid
turn intact, and playback begins within 300 ms of audio becoming available under normal
local conditions.

**Phase 2 — Transcription harness.** Add `faster-whisper` with push-to-talk. Do **not**
write the resolver yet. Log every raw transcript with the board FEN to `transcripts.jsonl`.
*Done when:* the user has recorded ≥50 spoken moves and the log is populated. This file is
the specification for Phase 3 — it reveals which squares actually get confused, whether
`"knight to f3"` outperforms `"Nf3"`, and whether NATO phonetics are needed.

**Phase 3 — Resolver.** Implement Section 6 against the real Phase 2 data. Add the
confirmation loop and the command router.
*Done when:* a full game is playable entirely by voice with no keyboard. **This is the
milestone that matters — stop and let the user play several games here.**

**Phase 4 — Coach.** Implement Section 7, PV-only version first. The user plays 20 games
and logs every comment that was vague or wrong; those failures determine which detectors
get written.
*Done when:* commentary fires on real mistakes and stays quiet otherwise.

**Phase 5 — Hands-free.** Silero VAD for turn-taking, openWakeWord to remove push-to-talk.
Pure UX; no new capability, which is why it is late.

**Phase 6 — Polish.** Takebacks, hints that describe the *type* of the best move rather
than the move, opening book so the first six moves are not Stockfish crushing a beginner.

---

## 9. Non-goals

- No native mobile application, multiplayer, or accounts.
- No public hosting, cloud runtime, or external API dependency.
- No fine-tuning or training of any model.
- No cloud deployment or Docker orchestration.
- No support for chess variants.

---

## 10. Start here

Phase 0 is implemented as the local browser application described above. Complete and
record its acceptance gate before starting Phase 1. Later phases must preserve the
browser interface, explicit state ownership, local-only runtime, and structured latency
instrumentation established in Phase 0.
