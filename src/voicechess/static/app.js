"use strict";

const PIECES = Object.freeze({
  K: { glyph: "♔", name: "white king", color: "white" },
  Q: { glyph: "♕", name: "white queen", color: "white" },
  R: { glyph: "♖", name: "white rook", color: "white" },
  B: { glyph: "♗", name: "white bishop", color: "white" },
  N: { glyph: "♘", name: "white knight", color: "white" },
  P: { glyph: "♙", name: "white pawn", color: "white" },
  k: { glyph: "♚", name: "black king", color: "black" },
  q: { glyph: "♛", name: "black queen", color: "black" },
  r: { glyph: "♜", name: "black rook", color: "black" },
  b: { glyph: "♝", name: "black bishop", color: "black" },
  n: { glyph: "♞", name: "black knight", color: "black" },
  p: { glyph: "♟", name: "black pawn", color: "black" },
});

const FILES = Object.freeze(["a", "b", "c", "d", "e", "f", "g", "h"]);
const RANKS = Object.freeze([8, 7, 6, 5, 4, 3, 2, 1]);

const elements = {
  board: document.querySelector("#chessboard"),
  engineBadge: document.querySelector("#engine-badge"),
  engineLabel: document.querySelector("#engine-label"),
  turnChip: document.querySelector("#turn-chip"),
  stateLabel: document.querySelector("#state-label"),
  statusMessage: document.querySelector("#status-message"),
  lastMove: document.querySelector("#last-move"),
  moveForm: document.querySelector("#move-form"),
  sanInput: document.querySelector("#san-input"),
  moveButton: document.querySelector("#move-button"),
  errorMessage: document.querySelector("#error-message"),
  moveHistory: document.querySelector("#move-history"),
  moveCount: document.querySelector("#move-count"),
  newGameButton: document.querySelector("#new-game-button"),
  resignButton: document.querySelector("#resign-button"),
  exportButton: document.querySelector("#export-button"),
  helpButton: document.querySelector("#help-button"),
  helpDialog: document.querySelector("#help-dialog"),
  closeHelpButton: document.querySelector("#close-help-button"),
};

let snapshot = null;
let busy = false;

class ApiError extends Error {
  constructor(message, code = "request_failed", status = 0) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function requestJson(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch (_error) {
    throw new ApiError("The local server could not be reached.", "network_error");
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && body.error;
    throw new ApiError(
      detail && detail.message ? detail.message : "The request could not be completed.",
      detail && detail.code ? detail.code : "request_failed",
      response.status,
    );
  }
  return body;
}

async function refreshHealth() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    const health = await response.json();
    const ready = Boolean(health.stockfish_ready);
    elements.engineBadge.dataset.status = ready ? "ready" : "unavailable";
    elements.engineLabel.textContent = ready ? "Stockfish ready" : "Stockfish unavailable";
  } catch (_error) {
    elements.engineBadge.dataset.status = "unavailable";
    elements.engineLabel.textContent = "Server unavailable";
  }
}

async function refreshGame() {
  snapshot = await requestJson("/api/game");
  renderSnapshot(snapshot);
}

function renderSnapshot(game) {
  renderBoard(game.board);
  renderHistory(game.moves);

  const turn = game.side_to_move === "white" ? "White" : "Black";
  elements.turnChip.textContent = game.status === "active" ? `${turn} to move` : "Game over";
  elements.stateLabel.textContent = humanize(game.state);
  elements.statusMessage.textContent = game.message;
  elements.lastMove.textContent = game.last_move
    ? `Last move: ${game.last_move}`
    : "No moves played yet";
  updateControls();
}

function renderBoard(board) {
  const fragment = document.createDocumentFragment();
  for (const rank of RANKS) {
    FILES.forEach((file, fileIndex) => {
      const squareName = `${file}${rank}`;
      const square = document.createElement("div");
      const isLight = (fileIndex + rank) % 2 === 0;
      square.className = `square ${isLight ? "square-light" : "square-dark"}`;
      square.setAttribute("role", "gridcell");
      square.dataset.square = squareName;

      const piece = PIECES[board[squareName]];
      square.setAttribute("aria-label", piece ? `${squareName}, ${piece.name}` : `${squareName}, empty`);
      if (piece) {
        const glyph = document.createElement("span");
        glyph.className = `piece piece-${piece.color}`;
        glyph.textContent = piece.glyph;
        glyph.setAttribute("aria-hidden", "true");
        square.appendChild(glyph);
      }

      if (file === "a") {
        square.appendChild(coordinate(String(rank), "rank"));
      }
      if (rank === 1) {
        square.appendChild(coordinate(file, "file"));
      }
      fragment.appendChild(square);
    });
  }

  elements.board.replaceChildren(fragment);
  elements.board.setAttribute("aria-busy", "false");
}

function coordinate(value, kind) {
  const label = document.createElement("span");
  label.className = `coordinate coordinate-${kind}`;
  label.textContent = value;
  label.setAttribute("aria-hidden", "true");
  return label;
}

function renderHistory(moves) {
  elements.moveCount.textContent = `${moves.length} ${moves.length === 1 ? "move" : "moves"}`;
  if (moves.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty-history";
    empty.textContent = "Moves will appear here.";
    elements.moveHistory.replaceChildren(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  for (let index = 0; index < moves.length; index += 2) {
    const row = document.createElement("li");
    row.className = "history-row";

    const number = document.createElement("span");
    number.className = "move-number";
    number.textContent = `${index / 2 + 1}.`;

    const white = document.createElement("span");
    white.textContent = moves[index];

    const black = document.createElement("span");
    black.textContent = moves[index + 1] || "";

    row.append(number, white, black);
    fragment.appendChild(row);
  }
  elements.moveHistory.replaceChildren(fragment);
  elements.moveHistory.scrollTop = elements.moveHistory.scrollHeight;
}

function updateControls() {
  const active = snapshot && snapshot.status === "active";
  const acceptingMove = active && snapshot.state === "PLAYER_INPUT";
  elements.sanInput.disabled = busy || !acceptingMove;
  elements.moveButton.disabled = busy || !acceptingMove;
  elements.moveButton.dataset.loading = String(busy);
  elements.newGameButton.disabled = busy;
  elements.resignButton.disabled = busy || !active;
  elements.exportButton.disabled = busy || !snapshot;
  elements.board.setAttribute("aria-busy", String(busy));
}

function setBusy(value, message = null) {
  busy = value;
  if (message) {
    elements.statusMessage.textContent = message;
  }
  updateControls();
}

function showError(error) {
  elements.errorMessage.textContent = error instanceof Error ? error.message : String(error);
  elements.errorMessage.hidden = false;
}

function clearError() {
  elements.errorMessage.hidden = true;
  elements.errorMessage.textContent = "";
}

function humanize(value) {
  return value.toLowerCase().replaceAll("_", " ");
}

async function runAction(action, thinkingMessage) {
  clearError();
  setBusy(true, thinkingMessage);
  try {
    snapshot = await action();
    renderSnapshot(snapshot);
    return true;
  } catch (error) {
    showError(error);
    try {
      await refreshGame();
    } catch (_refreshError) {
      // Keep the last safely rendered snapshot when refresh is unavailable.
    }
    return false;
  } finally {
    setBusy(false);
    await refreshHealth();
  }
}

elements.moveForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const san = elements.sanInput.value.trim();
  if (!san) {
    showError(new ApiError("Enter a move, for example e4 or Nf3.", "empty_san"));
    elements.sanInput.focus();
    return;
  }

  const succeeded = await runAction(
    () =>
      requestJson("/api/game/move", {
        method: "POST",
        body: JSON.stringify({ san }),
      }),
    "Stockfish is thinking…",
  );
  if (succeeded && snapshot && snapshot.state === "PLAYER_INPUT") {
    elements.sanInput.value = "";
    elements.sanInput.focus();
  }
});

elements.newGameButton.addEventListener("click", async () => {
  if (snapshot && snapshot.moves.length > 0 && !window.confirm("Start a new game?")) {
    return;
  }
  await runAction(
    () => requestJson("/api/game/new", { method: "POST", body: "{}" }),
    "Setting up a new board…",
  );
  elements.sanInput.value = "";
  elements.sanInput.focus();
});

elements.resignButton.addEventListener("click", async () => {
  if (!window.confirm("Resign this game?")) {
    return;
  }
  await runAction(
    () => requestJson("/api/game/resign", { method: "POST", body: "{}" }),
    "Recording resignation…",
  );
});

elements.exportButton.addEventListener("click", async () => {
  clearError();
  setBusy(true, "Preparing PGN…");
  try {
    const result = await requestJson("/api/game/export", { method: "POST", body: "{}" });
    const url = URL.createObjectURL(new Blob([result.pgn], { type: "application/x-chess-pgn" }));
    const download = document.createElement("a");
    download.href = url;
    download.download = result.filename;
    document.body.appendChild(download);
    download.click();
    download.remove();
    URL.revokeObjectURL(url);
    elements.statusMessage.textContent = `Exported ${result.filename}`;
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

elements.helpButton.addEventListener("click", () => elements.helpDialog.showModal());
elements.closeHelpButton.addEventListener("click", () => elements.helpDialog.close());
elements.helpDialog.addEventListener("click", (event) => {
  if (event.target === elements.helpDialog) {
    elements.helpDialog.close();
  }
});

async function initialize() {
  updateControls();
  await Promise.allSettled([refreshHealth(), refreshGame()]);
  if (!snapshot) {
    showError(new ApiError("The current game could not be loaded."));
  } else if (snapshot.state === "PLAYER_INPUT") {
    elements.sanInput.focus();
  }
}

void initialize();
