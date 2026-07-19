/**
 * V2WagerRoom.js — server-authoritative V2 PvP room.
 *
 * Lifecycle: lobby -> active -> complete
 *
 * Two human seats only. A match uses the lower available balance, capped at
 * 100 demo credits, so a normal loss does not strand a returning player.
 * The room owns one GameEngine, one wager, scores, revision, absolute
 * deadline, a map of socket->playerId, and a single server timer.
 *
 * Moves and bet actions are validated server-side exclusively; no client
 * logic is executed. Swaps have a 60-second deadline and betting turns have a
 * 30-second deadline. Exceeding either deadline forfeits the hand.
 *
 * Dead-board fix: after cascades and before arming the next actor, ensure the
 * board has at least one valid move; reshuffle/regenerate boundedly.
 */

import GameEngine from '../src/engine/GameEngine.js';
import {
  createWager,
  postAnte,
  recordStreetMove,
  applyBet,
  forfeit as forfeitWager,
  currentActor,
  currentMoveActor,
  DEFAULT_ANTE,
  WAGER_PHASE,
} from '../src/game/wagering.js';

const MAX_BUY_IN = 100;
const SWAP_DEADLINE_MS = 60_000;
const BETTING_DEADLINE_MS = 30_000;
const MAX_RESHUFLE_TRIES = 5;

export class V2WagerRoom {
  /**
   * @param {object} opts
   * @param {string} opts.code        — internal match id
   * @param {object} opts.ledger      — DemoCreditLedger instance
   * @param {Function} [opts.send]    — bounded server send helper
   */
  constructor({ code, ledger, send = (ws, message) => ws.send(JSON.stringify(message)) }) {
    this.code = code;
    this.ledger = ledger;
    this.send = send;
    this.lifecycle = 'lobby'; // 'lobby' | 'active' | 'complete'

    this.engine = new GameEngine();
    this.wager = null;
    /** @type {Record<string, number>} cumulative scores per seat id */
    this.scores = {};
    this.revision = 0;
    this.deadline = null; // absolute ms timestamp or null
    this._deadlineTimer = null;

    /** @type {Map<import('ws').WebSocket, string>} socket -> playerId */
    this.sockets = new Map();

    /** @type {Array<{ id: string, name: string }>} ordered seat registry (max 2) */
    this._seats = [];

    /** matchId for ledger escrow */
    this._escrowMatchId = null;
    this.buyIn = 0;
    this._settled = false;

    /** result object populated on COMPLETE */
    this.result = null;
    this.rematchRequestIds = new Set();
    this.presentation = null;
  }

  /* ------------------------------------------------------------------ */
  /*  Seat helpers                                                       */
  /* ------------------------------------------------------------------ */

  _seatIndex(playerId) {
    return this._seats.findIndex((s) => s.id === playerId);
  }

  _seatById(playerId) {
    return this._seats.find((s) => s.id === playerId) || null;
  }

  _isConnected(playerId) {
    for (const [, sid] of this.sockets) if (sid === playerId) return true;
    return false;
  }

  /* ------------------------------------------------------------------ */
  /*  Dead-board fix: ensure playable after cascades                     */
  /* ------------------------------------------------------------------ */

  _ensurePlayable() {
    if (this.engine.hasValidMoves()) return true;
    for (let tries = 0; tries < MAX_RESHUFLE_TRIES; tries++) {
      this.engine.reshuffle();
      if (this.engine.hasValidMoves()) return true;
    }
    // Last resort: reinitialize board
    this.engine.initBoard();
    return this.engine.hasValidMoves();
  }

  /* ------------------------------------------------------------------ */
  /*  Lifecycle transitions                                              */
  /* ------------------------------------------------------------------ */

  /**
   * Join a seat.  Two seats only.  Returns { ok } or { ok:false, error }.
   * Reconnect (same playerId already seated) is idempotent.
   */
  join(player) {
    if (this.lifecycle === 'complete') return { ok: false, error: 'Room complete' };

    const existingIdx = this._seatIndex(player.id);
    if (existingIdx !== -1) {
      // re-join OK — idempotent
      if (this._seats[existingIdx].name !== player.name) {
        this._seats[existingIdx].name = player.name;
      }
      return { ok: true };
    }

    if (this._seats.length >= 2) return { ok: false, error: 'Room full (2 seats)' };

    this._seats.push({ id: player.id, name: player.name });

    if (this._seats.length === 2) {
      // attempt auto-activation
      const activation = this._tryActivate();
      if (!activation.ok) {
        // rollback the seat
        this._seats.pop();
        return activation;
      }
    }

    return { ok: true };
  }

  /** Attempt to activate the room (reserve credits, start wager). */
  _tryActivate() {
    if (this.lifecycle !== 'lobby' || this._seats.length !== 2) {
      return { ok: false, error: 'Not ready' };
    }

    const matchId = `match_${this.code}_${Date.now()}`;

    // Restore only broke demo accounts, then use a fair shared stack capped at
    // 100. This mirrors a future wallet escrow without trusting client credits.
    for (const s of this._seats) {
      this.ledger.ensurePlayable(s.id, DEFAULT_ANTE);
    }
    const buyIn = Math.min(MAX_BUY_IN, ...this._seats.map((s) => this.ledger.getBalance(s.id)));
    if (buyIn < DEFAULT_ANTE) return { ok: false, error: 'Insufficient credits to post ante' };

    // reserve
    for (const s of this._seats) {
      this.ledger.reserve(s.id, buyIn, matchId);
    }

    this._escrowMatchId = matchId;
    this.buyIn = buyIn;

    // create wager
    this.wager = createWager({
      players: this._seats.map((s) => ({ id: s.id, name: s.name, kind: 'human' })),
      startingCoins: buyIn,
    });

    this.scores = {};
    for (const s of this._seats) this.scores[s.id] = 0;

    this.wager = this._syncScores(postAnte(this.wager));
    this.lifecycle = 'active';
    this.revision++;
    this.presentation = null;

    this._armDeadlineForAction();

    return { ok: true };
  }

  /* ------------------------------------------------------------------ */
  /*  Deadline timer                                                     */
  /* ------------------------------------------------------------------ */

  _clearDeadline() {
    if (this._deadlineTimer) {
      clearTimeout(this._deadlineTimer);
      this._deadlineTimer = null;
    }
    this.deadline = null;
  }

  _armDeadlineForAction() {
    this._clearDeadline();
    if (!this.wager || ![WAGER_PHASE.STREET_MOVE, WAGER_PHASE.BETTING].includes(this.wager.phase)) return;

    const deadlineMs = this.wager.phase === WAGER_PHASE.BETTING
      ? BETTING_DEADLINE_MS
      : SWAP_DEADLINE_MS;
    this.deadline = Date.now() + deadlineMs;
    const capturedRev = this.revision;
    const capturedCode = this.code;

    this._deadlineTimer = setTimeout(() => {
      this._onDeadline(capturedRev, capturedCode);
    }, deadlineMs);
  }

  _onDeadline(revAtArm, codeAtArm) {
    // guard: room may have changed
    if (this.code !== codeAtArm) return;
    if (this.lifecycle !== 'active') return;
    if (this.revision !== revAtArm) return; // action happened since timer was armed
    if (!this.wager) return;

    const actor = this.wager.phase === WAGER_PHASE.STREET_MOVE
      ? currentMoveActor(this.wager)
      : currentActor(this.wager);
    if (!actor) return;
    this.forfeit(actor.id, 'forfeits on time');
  }

  /* ------------------------------------------------------------------ */
  /*  Post-wager-change hook                                             */
  /* ------------------------------------------------------------------ */

  /** Called after every successful wager mutation. */
  _onWagerChanged() {
    if (!this.wager) return;

    if (this.wager.phase === WAGER_PHASE.COMPLETE) {
      this._settleLedger();
      this._clearDeadline();
      this.lifecycle = 'complete';
    } else if ([WAGER_PHASE.STREET_MOVE, WAGER_PHASE.BETTING].includes(this.wager.phase)) {
      this._armDeadlineForAction();
    } else {
      // ANTE, SHOWDOWN — no active player turn
      this._clearDeadline();
    }
  }

  /** Keep public wager seats in lockstep with the engine's cumulative scores. */
  _syncScores(wager) {
    return {
      ...wager,
      seats: wager.seats.map((seat) => ({
        ...seat,
        score: this.scores[seat.id] || 0,
      })),
    };
  }

  /** Project a server-calculated cascade into a display-only snapshot trace. */
  _setCascadePresentation(baseRevision, i, j, result) {
    this.presentation = {
      kind: 'cascade',
      baseRevision,
      revision: this.revision,
      swap: [i, j],
      steps: result.cascades.map((step) => ({
        matchedIndices: step.matched,
        points: step.points,
        afterCells: step.after.map((cell) => ({ type: cell.type, id: cell.id })),
      })),
    };
  }

  /* ------------------------------------------------------------------ */
  /*  Ledger settlement                                                  */
  /* ------------------------------------------------------------------ */

  _settleLedger() {
    if (this._settled || !this._escrowMatchId || !this.wager) return;
    this._settled = true;

    const payouts = {};
    for (const seat of this.wager.seats) {
      payouts[seat.id] = seat.coins;
    }

    this.ledger.settle(this._escrowMatchId, payouts);

    this.result = {
      winnerIds: this.wager.winnerIds,
      payouts,
    };
  }

  /* ------------------------------------------------------------------ */
  /*  Actions                                                            */
  /* ------------------------------------------------------------------ */

  /**
   * Attempt a match-3 move.
   *
   * @param {string} playerId
   * @param {number} i  — cell index
   * @param {number} j  — cell index
   * @param {number} expectedRevision
   * @returns {{ ok: boolean, error?: string }}
   */
  tryMove(playerId, i, j, expectedRevision) {
    if (this.lifecycle !== 'active') return { ok: false, error: 'Room not active' };
    if (this.revision !== expectedRevision) return { ok: false, error: 'Stale revision' };
    if (!this.wager) return { ok: false, error: 'No active wager' };
    if (!Number.isInteger(i) || !Number.isInteger(j)) return { ok: false, error: 'Invalid move indices' };

    if (this.wager.phase !== WAGER_PHASE.STREET_MOVE) {
      return { ok: false, error: `Expected STREET_MOVE, got ${this.wager.phase}` };
    }

    const expected = currentMoveActor(this.wager);
    if (!expected || expected.id !== playerId) {
      return { ok: false, error: 'Not your turn to move' };
    }

    // run engine
    const result = this.engine.processMove(i, j);
    if (!result.valid) return { ok: false, error: 'Invalid swap or no match' };

    // update cumulative score
    this.scores[playerId] = (this.scores[playerId] || 0) + result.score;

    // ensure playable board for next actor
    this._ensurePlayable();

    // record the street move
    this.wager = this._syncScores(recordStreetMove(this.wager, playerId, { ...this.scores }));
    this.revision++;
    this._setCascadePresentation(expectedRevision, i, j, result);

    this._onWagerChanged();
    this.broadcast();
    return { ok: true };
  }

  /**
   * Attempt a betting action.
   *
   * @param {string} playerId
   * @param {string} action   — 'check' | 'call' | 'raise' | 'fold'
   * @param {number} expectedRevision
   * @returns {{ ok: boolean, error?: string }}
   */
  tryBet(playerId, action, expectedRevision) {
    if (this.lifecycle !== 'active') return { ok: false, error: 'Room not active' };
    if (this.revision !== expectedRevision) return { ok: false, error: 'Stale revision' };
    if (!this.wager) return { ok: false, error: 'No active wager' };

    if (this.wager.phase !== WAGER_PHASE.BETTING) {
      return { ok: false, error: `Expected BETTING, got ${this.wager.phase}` };
    }

    const actor = currentActor(this.wager);
    if (!actor || actor.id !== playerId) {
      return { ok: false, error: 'Not your turn to bet' };
    }

    const prevWager = this.wager;
    const nextWager = applyBet(this.wager, playerId, action);

    // reject no-ops / illegal actions
    if (nextWager === prevWager) {
      return { ok: false, error: `Illegal or no-op action: ${action}` };
    }
    this.wager = this._syncScores(nextWager);

    this.revision++;
    this.presentation = null;
    this._onWagerChanged();
    this.broadcast();
    return { ok: true };
  }

  /** Forfeit a seated player during any active phase and settle exactly once. */
  forfeit(playerId, reason = 'forfeits') {
    if (this.lifecycle !== 'active') return { ok: false, error: 'Room not active' };
    if (!this.wager) return { ok: false, error: 'No active wager' };
    if (this._seatIndex(playerId) === -1) return { ok: false, error: 'Player is not seated' };

    const nextWager = forfeitWager(this.wager, playerId, reason);
    if (nextWager === this.wager) return { ok: false, error: 'Unable to forfeit player' };

    this.wager = this._syncScores(nextWager);
    this.revision++;
    this.presentation = null;
    this._onWagerChanged();
    this.broadcast();
    return { ok: true };
  }

  /** Record one player's consent to start a fresh match with the same seats. */
  requestRematch(playerId) {
    if (this.lifecycle !== 'complete' || !this._settled) {
      return { ok: false, error: 'Rematch is available after a settled hand' };
    }
    if (this._seatIndex(playerId) === -1) {
      return { ok: false, error: 'Only match players can request a rematch' };
    }

    this.rematchRequestIds.add(playerId);
    return {
      ok: true,
      agreed: this.rematchRequestIds.size === this._seats.length,
    };
  }

  /* ------------------------------------------------------------------ */
  /*  Snapshot + broadcast                                               */
  /* ------------------------------------------------------------------ */

  /**
   * Per-player serializable snapshot.  Omits implementation-private
   * internals.
   */
  snapshotFor(playerId) {
    const seatIdx = this._seatIndex(playerId);
    const snap = {
      type: 'V2_SNAPSHOT',
      revision: this.revision,
      serverTime: Date.now(),
      lifecycle: this.lifecycle,
      buyIn: this.buyIn,
      cells: this.engine.cells.map((c) => ({ type: c.type, id: c.id })),
      wager: this.wager,
      players: this._seats.map((s) => ({
        id: s.id,
        name: s.name,
        connected: this._isConnected(s.id),
      })),
      self: {
        id: playerId,
        credits: this.ledger.getBalance(playerId) + this.ledger.getEscrowedBalance(playerId, this._escrowMatchId),
        seat: seatIdx !== -1 ? seatIdx : null,
      },
      activeSeatId: null,
      deadline: this.deadline,
      result: this.result,
      rematch: this.lifecycle === 'complete' && this._settled
        ? { requestedSeatIds: [...this.rematchRequestIds] }
        : null,
      presentation: this.presentation?.revision === this.revision ? this.presentation : null,
    };

    // current actor / move actor
    if (this.wager && this.lifecycle === 'active') {
      if (this.wager.phase === WAGER_PHASE.BETTING) {
        const a = currentActor(this.wager);
        snap.activeSeatId = a ? a.id : null;
      } else if (this.wager.phase === WAGER_PHASE.STREET_MOVE) {
        const m = currentMoveActor(this.wager);
        snap.activeSeatId = m ? m.id : null;
      }
    }

    return snap;
  }

  /** Send per-socket snapshot to every connected socket. */
  broadcast() {
    for (const [ws, pid] of this.sockets) {
      if (ws.readyState === 1) {
        const snap = this.snapshotFor(pid);
        this.send(ws, snap);
      }
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Socket management                                                  */
  /* ------------------------------------------------------------------ */

  addSocket(ws, playerId) {
    this.sockets.set(ws, playerId);
  }

  removeSocket(ws) {
    this.sockets.delete(ws);
  }

  /**
   * Close the match: clear timer, refund unreserved escrow, and sever this
   * match's socket bindings. WebSocket connections stay open so players can
   * return to the presence lobby without receiving a new guest identity.
   */
  close() {
    this._clearDeadline();
    if (this._escrowMatchId && !this._settled) {
      this.ledger.refund(this._escrowMatchId);
    }
    this.sockets.clear();
    this.rematchRequestIds.clear();
    this.lifecycle = 'complete';
  }
}

export default V2WagerRoom;
