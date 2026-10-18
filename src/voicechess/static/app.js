"use strict";

// Both colours use the solid glyphs; CSS colours them. Solid shapes read far
// better than the outline set, which looks hollow on light squares.
const PIECES = Object.freeze({
  K: { glyph: "♚", name: "white king", color: "white" },
  Q: { glyph: "♛", name: "white queen", color: "white" },
  R: { glyph: "♜", name: "white rook", color: "white" },
  B: { glyph: "♝", name: "white bishop", color: "white" },
  N: { glyph: "♞", name: "white knight", color: "white" },
  P: { glyph: "♟", name: "white pawn", color: "white" },
  k: { glyph: "♚", name: "black king", color: "black" },
  q: { glyph: "♛", name: "black queen", color: "black" },
  r: { glyph: "♜", name: "black rook", color: "black" },
  b: { glyph: "♝", name: "black bishop", color: "black" },
  n: { glyph: "♞", name: "black knight", color: "black" },
  p: { glyph: "♟", name: "black pawn", color: "black" },
});

// Variation selector 15: asks for the text glyph, not the emoji pawn some
// platforms substitute for U+265F.
const TEXT_PRESENTATION = String.fromCodePoint(0xfe0e);

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
  modeStatus: document.querySelector("#mode-status"),
  manualModeButton: document.querySelector("#manual-mode-button"),
  voiceModeButton: document.querySelector("#voice-mode-button"),
  manualModeNote: document.querySelector("#manual-mode-note"),
  voiceModeNote: document.querySelector("#voice-mode-note"),
  errorMessage: document.querySelector("#error-message"),
  moveHistory: document.querySelector("#move-history"),
  moveCount: document.querySelector("#move-count"),
  newGameButton: document.querySelector("#new-game-button"),
  resignButton: document.querySelector("#resign-button"),
  exportButton: document.querySelector("#export-button"),
  helpButton: document.querySelector("#help-button"),
  helpDialog: document.querySelector("#help-dialog"),
  closeHelpButton: document.querySelector("#close-help-button"),
  promotionDialog: document.querySelector("#promotion-dialog"),
};

let snapshot = null;
let busy = false;
let inputMode = "manual";
let selectedSquare = null;
let pointerDrag = null;
let suppressNextClick = false;

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
  elements.turnChip.dataset.side = game.status === "active" ? game.side_to_move : "over";
  elements.stateLabel.textContent = humanize(game.state);
  elements.statusMessage.textContent = game.message;
  elements.lastMove.textContent = game.last_move
    ? `Last move: ${game.last_move}`
    : "No moves played yet";
  updateControls();
}

function renderBoard(board) {
  const fragment = document.createDocumentFragment();
  const interactive = canSubmitManualMove();
  for (const rank of RANKS) {
    FILES.forEach((file, fileIndex) => {
      const squareName = `${file}${rank}`;
      const square = document.createElement("div");
      const isLight = (fileIndex + rank) % 2 === 0;
      square.className = `square ${isLight ? "square-light" : "square-dark"}`;
      square.setAttribute("role", "gridcell");
      square.dataset.square = squareName;

      const piece = PIECES[board[squareName]];
      const owned = Boolean(piece && piece.color === "white");
      square.dataset.owned = String(owned);
      square.tabIndex = interactive ? 0 : -1;
      square.setAttribute("aria-selected", String(selectedSquare === squareName));
      if (selectedSquare === squareName) {
        square.classList.add("square-selected");
      }
      square.setAttribute("aria-label", piece ? `${squareName}, ${piece.name}` : `${squareName}, empty`);
      if (piece) {
        const glyph = document.createElement("span");
        glyph.className = `piece piece-${piece.color}`;
        // U+FE0E asks for the text glyph, not the emoji pawn some platforms substitute.
        glyph.textContent = piece.glyph + TEXT_PRESENTATION;
        glyph.setAttribute("aria-hidden", "true");
        glyph.dataset.draggable = String(interactive && owned);
        if (owned) {
          glyph.addEventListener("pointerdown", (event) => beginPointerDrag(event, squareName));
        }
        square.appendChild(glyph);
      }

      square.addEventListener("click", () => selectBoardSquare(squareName));
      square.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectBoardSquare(squareName);
        }
      });
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
  elements.board.dataset.interactive = String(interactive);
}

function coordinate(value, kind) {
  const label = document.createElement("span");
  label.className = `coordinate coordinate-${kind}`;
  label.textContent = value;
  label.setAttribute("aria-hidden", "true");
  return label;
}

function canSubmitManualMove() {
  return Boolean(
    inputMode === "manual" &&
      !busy &&
      snapshot &&
      snapshot.status === "active" &&
      snapshot.state === "PLAYER_INPUT" &&
      snapshot.side_to_move === "white",
  );
}

function selectBoardSquare(squareName) {
  if (suppressNextClick) {
    suppressNextClick = false;
    return;
  }
  if (!canSubmitManualMove()) {
    return;
  }

  const piece = snapshot.board[squareName];
  const isOwnedPiece = Boolean(piece && PIECES[piece].color === "white");
  if (selectedSquare === null) {
    if (!isOwnedPiece) {
      return;
    }
    selectedSquare = squareName;
    renderBoard(snapshot.board);
    focusSquare(squareName);
    return;
  }

  if (selectedSquare === squareName) {
    selectedSquare = null;
    renderBoard(snapshot.board);
    focusSquare(squareName);
    return;
  }

  if (isOwnedPiece) {
    selectedSquare = squareName;
    renderBoard(snapshot.board);
    focusSquare(squareName);
    return;
  }

  void submitBoardMove(selectedSquare, squareName);
}

function focusSquare(squareName) {
  elements.board.querySelector(`[data-square="${squareName}"]`)?.focus();
}

function beginPointerDrag(event, squareName) {
  if (!canSubmitManualMove() || event.button !== 0) {
    return;
  }
  pointerDrag = {
    pointerId: event.pointerId,
    sourceSquare: squareName,
    startX: event.clientX,
    startY: event.clientY,
    moved: false,
    piece: event.currentTarget,
    target: null,
  };
  event.currentTarget.setPointerCapture(event.pointerId);
  event.currentTarget.addEventListener("pointermove", movePointerDrag);
  event.currentTarget.addEventListener("pointerup", finishPointerDrag);
  event.currentTarget.addEventListener("pointercancel", cancelPointerDrag);
}

function movePointerDrag(event) {
  if (pointerDrag === null || pointerDrag.pointerId !== event.pointerId) {
    return;
  }
  const deltaX = event.clientX - pointerDrag.startX;
  const deltaY = event.clientY - pointerDrag.startY;
  if (!pointerDrag.moved && Math.hypot(deltaX, deltaY) < 6) {
    return;
  }

  event.preventDefault();
  pointerDrag.moved = true;
  selectedSquare = pointerDrag.sourceSquare;
  pointerDrag.piece.classList.add("piece-dragging");
  pointerDrag.piece.style.setProperty("--drag-x", `${deltaX}px`);
  pointerDrag.piece.style.setProperty("--drag-y", `${deltaY}px`);
  elements.board
    .querySelector(`[data-square="${pointerDrag.sourceSquare}"]`)
    ?.classList.add("square-selected");

  const target = document
    .elementsFromPoint(event.clientX, event.clientY)
    .find((element) => element.classList.contains("square"));
  pointerDrag.target?.classList.remove("square-drop-target");
  pointerDrag.target = target || null;
  if (pointerDrag.target?.dataset.square !== pointerDrag.sourceSquare) {
    pointerDrag.target?.classList.add("square-drop-target");
  }
}

function finishPointerDrag(event) {
  if (pointerDrag === null || pointerDrag.pointerId !== event.pointerId) {
    return;
  }
  const sourceSquare = pointerDrag.sourceSquare;
  const targetSquare = pointerDrag.target?.dataset.square || null;
  const moved = pointerDrag.moved;
  cleanUpPointerDrag();
  if (!moved) {
    return;
  }

  suppressNextClick = true;
  selectedSquare = null;
  requestAnimationFrame(() => {
    suppressNextClick = false;
  });
  if (targetSquare && targetSquare !== sourceSquare && canSubmitManualMove()) {
    void submitBoardMove(sourceSquare, targetSquare);
  } else if (snapshot) {
    renderBoard(snapshot.board);
  }
}

function cancelPointerDrag(event) {
  if (pointerDrag === null || pointerDrag.pointerId !== event.pointerId) {
    return;
  }
  cleanUpPointerDrag();
  selectedSquare = null;
  if (snapshot) {
    renderBoard(snapshot.board);
  }
}

function cleanUpPointerDrag() {
  const drag = pointerDrag;
  if (drag === null) {
    return;
  }
  drag.target?.classList.remove("square-drop-target");
  drag.piece.classList.remove("piece-dragging");
  drag.piece.style.removeProperty("--drag-x");
  drag.piece.style.removeProperty("--drag-y");
  drag.piece.removeEventListener("pointermove", movePointerDrag);
  drag.piece.removeEventListener("pointerup", finishPointerDrag);
  drag.piece.removeEventListener("pointercancel", cancelPointerDrag);
  if (drag.piece.hasPointerCapture(drag.pointerId)) {
    drag.piece.releasePointerCapture(drag.pointerId);
  }
  pointerDrag = null;
}

async function submitBoardMove(sourceSquare, targetSquare) {
  let promotion = null;
  if (snapshot.board[sourceSquare] === "P" && targetSquare.endsWith("8")) {
    promotion = await choosePromotion();
    if (promotion === null) {
      selectedSquare = null;
      renderBoard(snapshot.board);
      return;
    }
  }

  selectedSquare = null;
  await runAction(
    () =>
      requestJson("/api/game/move", {
        method: "POST",
        body: JSON.stringify({
          from_square: sourceSquare,
          to_square: targetSquare,
          promotion,
        }),
      }),
    "Stockfish is thinking…",
  );
}

function choosePromotion() {
  elements.promotionDialog.returnValue = "";
  elements.promotionDialog.showModal();
  return new Promise((resolve) => {
    elements.promotionDialog.addEventListener(
      "close",
      () => {
        const value = elements.promotionDialog.returnValue;
        resolve(["q", "r", "b", "n"].includes(value) ? value : null);
      },
      { once: true },
    );
  });
}

function setInputMode(mode) {
  inputMode = mode;
  selectedSquare = null;
  if (pointerDrag !== null) {
    cleanUpPointerDrag();
  }
  elements.modeStatus.textContent = mode === "manual" ? "Manual" : "Voice planned";
  elements.manualModeButton.setAttribute("aria-pressed", String(mode === "manual"));
  elements.voiceModeButton.setAttribute("aria-pressed", String(mode === "voice"));
  elements.manualModeNote.hidden = mode !== "manual";
  elements.voiceModeNote.hidden = mode !== "voice";
  clearError();
  updateControls();
  if (snapshot) {
    renderBoard(snapshot.board);
  }
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
  elements.manualModeButton.disabled = busy;
  elements.voiceModeButton.disabled = busy;
  elements.newGameButton.disabled = busy;
  elements.resignButton.disabled = busy || !active;
  elements.exportButton.disabled = busy || !snapshot;
  elements.board.setAttribute("aria-busy", String(busy));
  const boardInteractive = canSubmitManualMove();
  elements.board.dataset.interactive = String(boardInteractive);
  for (const square of elements.board.querySelectorAll(".square")) {
    square.tabIndex = boardInteractive ? 0 : -1;
  }
  for (const piece of elements.board.querySelectorAll('.square[data-owned="true"] .piece')) {
    piece.dataset.draggable = String(boardInteractive);
  }
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

elements.manualModeButton.addEventListener("click", () => setInputMode("manual"));
elements.voiceModeButton.addEventListener("click", () => setInputMode("voice"));

elements.newGameButton.addEventListener("click", async () => {
  if (snapshot && snapshot.moves.length > 0 && !window.confirm("Start a new game?")) {
    return;
  }
  await runAction(
    () => requestJson("/api/game/new", { method: "POST", body: "{}" }),
    "Setting up a new board…",
  );
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
  }
}

void initialize();
