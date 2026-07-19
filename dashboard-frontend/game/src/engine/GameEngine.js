/**
 * GameEngine — Off-chain match-3 with persistent gem IDs
 *              and step-by-step cascade API for animation.
 *
 * Board: 8×8, 5 gem types (BTC, ETH, XRP, EOS, LTC)
 * Mechanics: swap adjacent → match 3+ → score → gravity → refill → cascade
 */

const BOARD_SIZE = 8;
const NUM_TYPES = 5;
const GEM_NAMES = ['btc', 'eth', 'xrp', 'eos', 'ltc'];
const GEM_COLORS = ['blue', 'red', 'green', 'yellow', 'orange'];
const MAX_TURNS = 999;

/* ------------------------------------------------------------------ */
/*  Cell                                                               */
/* ------------------------------------------------------------------ */

class Cell {
  constructor(type, id) {
    this.type = type;            // 0..4 = gem, -1 = empty
    this.id = id;                // assigned by the owning engine's id counter
  }
  clone() { return new Cell(this.type, this.id); }
  get color() { return GEM_COLORS[this.type]; }
  get name()  { return GEM_NAMES[this.type]; }
}

/* ------------------------------------------------------------------ */
/*  StepResult returned by runCascadeStep()                            */
/* ------------------------------------------------------------------ */

class StepResult {
  constructor() {
    this.matched = [];       // indices that were matched
    this.points = 0;         // score for this step
    this.before = [];        // Cell[] snapshot before removal
    this.after  = [];        // Cell[] snapshot after gravity+fill
    this.chainMatched = [];  // next cascade's matched indices (empty = no chain)
    this.hasChain = false;
    this.gameOver = false;
  }
}

/* ------------------------------------------------------------------ */
/*  GameEngine                                                        */
/* ------------------------------------------------------------------ */

class GameEngine {
  constructor(size = BOARD_SIZE, random = Math.random) {
    this.size = size;
    this.totalCells = size * size;
    this._nextId = 0;            // instance-local id counter (no global shared state)
    this._random = random;
    /** @type {Cell[]} */
    this.cells = [];
    this.score = 0;
    this.turn = 0;
    this.maxTurns = MAX_TURNS;
    this.gameOver = false;
    this.initBoard();
  }

  _freshId() { return ++this._nextId; }

  /* -- accessors -- */

  get board() { return this.cells.map(c => c.type); }

  /* ------------------------------------------------------------------ */
  /*  Init                                                              */
  /* ------------------------------------------------------------------ */

  initBoard() {
    this._nextId = 0;
    this.cells = [];
    for (let i = 0; i < this.totalCells; i++) {
      let t;
      do { t = Math.floor(this._random() * NUM_TYPES); }
      while (this._matchAtInit(i, t));
      this.cells[i] = new Cell(t, this._freshId());
    }
    if (!this.hasValidMoves()) this.initBoard();
  }

  _matchAtInit(pos, type) {
    const r = Math.floor(pos / this.size), c = pos % this.size;
    if (c >= 2 && this.cells[pos - 1]?.type === type && this.cells[pos - 2]?.type === type) return true;
    if (r >= 2 && this.cells[pos - this.size]?.type === type && this.cells[pos - this.size * 2]?.type === type) return true;
    return false;
  }

  /* ------------------------------------------------------------------ */
  /*  Swap + adjacency check                                            */
  /* ------------------------------------------------------------------ */

  isValidSwap(i, j) {
    if (i < 0 || i >= this.totalCells || j < 0 || j >= this.totalCells || i === j) return false;
    const ri = Math.floor(i / this.size), ci = i % this.size;
    const rj = Math.floor(j / this.size), cj = j % this.size;
    return Math.abs(ri - rj) + Math.abs(ci - cj) === 1;
  }

  swapCells(i, j) {
    const t = this.cells[i];
    this.cells[i] = this.cells[j];
    this.cells[j] = t;
  }

  /* ------------------------------------------------------------------ */
  /*  Match detection                                                   */
  /* ------------------------------------------------------------------ */

  findMatches() {
    const s = new Set();
    // horizontal
    for (let r = 0; r < this.size; r++) {
      for (let c = 0; c < this.size - 2; c++) {
        const idx = r * this.size + c;
        const t = this.cells[idx].type;
        if (t === -1) continue;
        if (this.cells[idx + 1].type === t && this.cells[idx + 2].type === t) {
          let end = c + 2;
          while (end + 1 < this.size && this.cells[r * this.size + end + 1].type === t) end++;
          for (let k = c; k <= end; k++) s.add(r * this.size + k);
        }
      }
    }
    // vertical
    for (let c = 0; c < this.size; c++) {
      for (let r = 0; r < this.size - 2; r++) {
        const idx = r * this.size + c;
        const t = this.cells[idx].type;
        if (t === -1) continue;
        if (this.cells[idx + this.size].type === t && this.cells[idx + this.size * 2].type === t) {
          let end = r + 2;
          while (end + 1 < this.size && this.cells[(end + 1) * this.size + c].type === t) end++;
          for (let k = r; k <= end; k++) s.add(k * this.size + c);
        }
      }
    }
    return [...s].sort((a, b) => a - b);
  }

  /* ------------------------------------------------------------------ */
  /*  Cascade internals                                                 */
  /* ------------------------------------------------------------------ */

  _removeMatches(indices) {
    for (const i of indices) this.cells[i].type = -1;
  }

  _applyGravity() {
    for (let c = 0; c < this.size; c++) {
      const stack = [];
      for (let r = this.size - 1; r >= 0; r--) {
        const idx = r * this.size + c;
        if (this.cells[idx].type !== -1) stack.push(this.cells[idx]);
      }
      while (stack.length < this.size) stack.push(new Cell(-1, this._freshId()));
      stack.reverse();
      for (let r = 0; r < this.size; r++) this.cells[r * this.size + c] = stack[r];
    }
  }

  _fillEmpty() {
    for (let i = 0; i < this.totalCells; i++) {
      if (this.cells[i].type === -1) this.cells[i] = new Cell(Math.floor(this._random() * NUM_TYPES), this._freshId());
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Step-by-step move API (for animation)                             */
  /* ------------------------------------------------------------------ */

  /**
   * Phase 1: attempt a swap.
   * @returns {{ matchedIndices: number[], points: number } | null}
   *   null means the swap is invalid or produces no match.
   */
  beginMove(i, j) {
    if (!this.isValidSwap(i, j)) return null;
    this.swapCells(i, j);
    const m = this.findMatches();
    if (m.length === 0) {
      this.swapCells(i, j); // swap back
      return null;
    }
    return { matchedIndices: m, points: m.length };
  }

  /**
   * Phase 2: resolve one cascade step.
   * Removes matched gems, applies gravity, fills empty cells.
   * Does NOT increment turn (all cascades = 1 turn).
   * @param {number[]} matchedIndices
   * @returns {StepResult}
   */
  runCascadeStep(matchedIndices) {
    const r = new StepResult();
    r.matched = [...matchedIndices];
    r.points = matchedIndices.length;
    r.before = this.cells.map(c => c.clone());

    this._removeMatches(matchedIndices);
    this._applyGravity();
    this._fillEmpty();

    r.after = this.cells.map(c => c.clone());
    this.score += r.points;

    const next = this.findMatches();
    r.chainMatched = next;
    r.hasChain = next.length > 0;
    r.gameOver = this.turn >= this.maxTurns;
    return r;
  }

  /**
   * Call after all cascade steps finish to advance the turn.
   */
  endTurn() {
    this.turn++;
    this.gameOver = this.turn >= this.maxTurns;
  }

  /* ------------------------------------------------------------------ */
  /*  One-shot move (no intermediate animation data)                    */
  /* ------------------------------------------------------------------ */

  processMove(i, j) {
    const initial = this.beginMove(i, j);
    if (!initial) return { valid: false, score: 0, totalScore: this.score, turn: this.turn, gameOver: this.gameOver, cascades: [] };

    const cascades = [];
    let m = initial.matchedIndices;
    let totalScore = 0;
    let safety = 0;

    while (m.length > 0 && safety < 20) {
      const step = this.runCascadeStep(m);
      totalScore += step.points;
      cascades.push(step);
      m = step.chainMatched;
      safety++;
    }

    this.endTurn();
    return {
      valid: true,
      score: totalScore,
      totalScore: this.score,
      turn: this.turn,
      gameOver: this.gameOver,
      cascades,
    };
  }

  /* ------------------------------------------------------------------ */
  /*  Utilities                                                          */
  /* ------------------------------------------------------------------ */

  hasValidMoves() {
    for (let i = 0; i < this.totalCells; i++) {
      for (let j = i + 1; j < this.totalCells; j++) {
        if (!this.isValidSwap(i, j)) continue;
        this.swapCells(i, j);
        const ok = this.findMatches().length > 0;
        this.swapCells(i, j);
        if (ok) return true;
      }
    }
    return false;
  }

  /**
   * Enumerate every valid adjacent swap that produces at least one match.
   * @returns {Array<[number, number]>} list of [i, j] cell-index pairs
   */
  getValidMoves() {
    const moves = [];
    for (let i = 0; i < this.totalCells; i++) {
      for (let j = i + 1; j < this.totalCells; j++) {
        if (!this.isValidSwap(i, j)) continue;
        this.swapCells(i, j);
        const ok = this.findMatches().length > 0;
        this.swapCells(i, j);
        if (ok) moves.push([i, j]);
      }
    }
    return moves;
  }

  /** Re-roll the board when no valid moves remain (preserves score/turn). */
  reshuffle() {
    // Keep score & turn, just re-init the board
    const oldScore = this.score;
    const oldTurn  = this.turn;
    this.initBoard();
    this.score = oldScore;
    this.turn  = oldTurn;
  }

  reset() {
    this.score = 0;
    this.turn = 0;
    this.gameOver = false;
    this.initBoard();
  }

  static get BOARD_SIZE() { return BOARD_SIZE; }
  static get NUM_TYPES()  { return NUM_TYPES; }
  static get GEM_COLORS() { return GEM_COLORS; }
  static get GEM_NAMES()  { return GEM_NAMES; }
}

export { GameEngine as default, Cell, StepResult, GEM_NAMES, GEM_COLORS };
