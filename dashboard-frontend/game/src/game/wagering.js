/**
 * wagering.js — V2 Hold'em-structured wagering layer (PURE, demo-coin only).
 *
 * This module owns ONLY the betting state machine: ante -> streets
 * (flop/turn/river) -> per-street move + betting round -> showdown. It is
 * deliberately separate from the match-3 engine and from any UI. The engine
 * (GameEngine) owns board/score; this owns coins/pot/actions.
 *
 * DESIGN CONSTRAINTS (from PLAN_2.0.md + advisor review):
 *  - Demo coins ONLY. No real money, no token, no entry fee. `stake` is a
 *    non-purchasable, non-transferable, non-redeemable in-game credit.
 *  - No blockchain. RNG and settlement are server/authoritative; this reducer
 *    is pure and deterministic so it can run client-side for PvA and server-side
 *    for PvP identically.
 *  - One move per street, interleaved (fixes the original "slow turns" problem).
 *  - Max ONE raise per street (keeps closure simple + avoids bet escalation).
 *  - Fold always available (the escape valve that keeps it skill, not chance).
 *  - Auto-action on timeout = CHECK if free, else FOLD (never involuntarily
 *    increases a player's exposure after disconnect).
 *
 * Phases:
 *   ANTE -> STREET_MOVE -> BETTING -> (next street) ... -> SHOWDOWN -> COMPLETE
 * Each street has one move per player, then one betting round. A called river
 * raise unlocks one final bonus move per live player, followed by showdown with
 * no additional betting.
 */

export const WAGER_PHASE = {
  ANTE: 'ante',
  STREET_MOVE: 'street_move', // players each make their one swap of this street
  BETTING: 'betting', // one betting round for the street
  SHOWDOWN: 'showdown',
  COMPLETE: 'complete',
};

// Streets in order. 3 streets => 3 moves per player (flop/turn/river).
export const STREETS = ['flop', 'turn', 'river'];

export const BET_ACTION = {
  CHECK: 'check',
  CALL: 'call',
  RAISE: 'raise',
  FOLD: 'fold',
};

export const DEFAULT_ANTE = 10;
export const DEFAULT_RAISE = 10;

/**
 * Create a fresh wagering state for a 2-player (or N) match.
 * @param {Array<{id:string,name:string,kind?:string,coins?:number}>} players
 * @param {object} opts { ante, raise, startingCoins }
 */
export function createWager({ players, ante = DEFAULT_ANTE, raise = DEFAULT_RAISE, startingCoins = 100 }) {
  const seats = players.map((p) => ({
    id: p.id,
    name: p.name,
    kind: p.kind || 'human',
    coins: p.coins != null ? p.coins : startingCoins,
    committed: 0, // coins committed to the pot this hand
    folded: false,
    actedThisStreet: false, // has acted in the current betting round
    totalCommitted: 0, // coins committed across the whole hand (for display)
    score: 0, // accumulated match-3 points (what decides the pot at showdown)
  }));
  return {
    phase: WAGER_PHASE.ANTE,
    streetIndex: -1, // -1 = pre-ante; 0 = flop; 1 = turn; 2 = river
    street: null,
    seats,
    pot: 0,
    currentBet: 0, // highest committed amount this betting round
    lastRaiserId: null,
    raiseCountThisStreet: 0,
    ante,
    raise,
    moveKind: 'street', // 'street' | 'river_bonus'
    moveSeatIds: seats.map((s) => s.id),
    movesThisStreet: 0, // how many players have made their swap this street
    requiredMovesThisStreet: seats.length, // one swap each
    history: [], // auditable log of actions
    winnerIds: [],
    settled: false,
    log: [], // human-readable log lines
  };
}

function clone(w) {
  return {
    ...w,
    seats: w.seats.map((s) => ({ ...s })),
    moveSeatIds: [...(w.moveSeatIds || [])],
    history: w.history,
    log: w.log,
  };
}

function pushLog(w, line) {
  w.log = [...w.log, line];
}

function syncScores(w, scores) {
  for (const s of w.seats) {
    const v = scores[s.id];
    if (Number.isFinite(v)) s.score = Math.max(0, Math.trunc(v));
  }
}

function activeSeats(w) {
  return w.seats.filter((s) => !s.folded);
}

function bettingActor(w) {
  // The first non-folded seat that has NOT acted this street, in seat order.
  const order = [...w.seats];
  for (const s of order) {
    if (!s.folded && !s.actedThisStreet) return s;
  }
  return null;
}

/** Seat whose swap is expected in the current move round. */
export function currentMoveActor(w) {
  if (!w || w.phase !== WAGER_PHASE.STREET_MOVE) return null;
  const ids = w.moveSeatIds?.length
    ? w.moveSeatIds
    : activeSeats(w).map((s) => s.id);
  const id = ids[w.movesThisStreet];
  return id ? w.seats.find((s) => s.id === id && !s.folded) || null : null;
}

/**
 * ANTE step: every seat posts the ante, pot forms, move to flop street.
 * Pure: returns a new wager state.
 */
export function postAnte(w) {
  if (w.phase !== WAGER_PHASE.ANTE) return w;
  if (w.seats.some((s) => s.coins < w.ante)) return w;
  const next = clone(w);
  for (const s of next.seats) {
    const amt = Math.min(s.coins, w.ante);
    s.coins -= amt;
    s.committed = amt;
    s.totalCommitted += amt;
  }
  next.pot = next.seats.reduce((sum, s) => sum + s.committed, 0);
  next.currentBet = w.ante;
  next.streetIndex = 0;
  next.street = STREETS[0];
  next.moveKind = 'street';
  next.moveSeatIds = activeSeats(next).map((s) => s.id);
  next.movesThisStreet = 0;
  next.requiredMovesThisStreet = next.moveSeatIds.length;
  next.phase = WAGER_PHASE.STREET_MOVE;
  next.raiseCountThisStreet = 0;
  next.lastRaiserId = null;
  for (const s of next.seats) s.actedThisStreet = false;
  pushLog(next, `Ante posted. Pot = ${next.pot}. Street: ${next.street}.`);
  return next;
}

/**
 * Record a player's swap for the current street (board/score handled by engine).
 * Once every seat has moved, transition to BETTING.
 */
export function recordStreetMove(w, actorId, scores = {}) {
  if (w.phase !== WAGER_PHASE.STREET_MOVE) return w;
  const expected = currentMoveActor(w);
  if (!expected || expected.id !== actorId) return w;
  const next = clone(w);
  syncScores(next, scores);
  next.movesThisStreet += 1;
  pushLog(next, `${seatName(next, actorId)} moved (${next.moveKind === 'river_bonus' ? 'final bonus swap' : `street ${next.street}`}).`);
  if (next.movesThisStreet >= next.requiredMovesThisStreet) {
    if (next.moveKind === 'river_bonus') {
      next.phase = WAGER_PHASE.SHOWDOWN;
      pushLog(next, `Final bonus swaps complete. Showdown. Pot = ${next.pot}.`);
      return showdown(next, scores);
    }
    // begin betting round
    next.phase = WAGER_PHASE.BETTING;
    for (const s of next.seats) {
      s.actedThisStreet = false;
      s.committed = 0; // new betting round: the ante already sits in the pot
    }
    next.currentBet = 0; // fresh betting round; first action is a bet/check
    next.raiseCountThisStreet = 0;
    next.lastRaiserId = null;
    pushLog(next, `Betting round — ${seatName(next, bettingActor(next)?.id)} to act.`);
  }
  return next;
}

/**
 * Apply a betting action. `amount` is relevant for CALL/RAISE.
 * Pure; returns new wager state.
 */
export function applyBet(w, actorId, action) {
  if (w.phase !== WAGER_PHASE.BETTING) return w;
  const actor = w.seats.find((s) => s.id === actorId);
  if (!actor || actor.folded || actor.actedThisStreet) return w;
  const expected = bettingActor(w);
  if (!expected || expected.id !== actorId) return w; // out of turn

  const next = clone(w);
  const a = next.seats.find((s) => s.id === actorId);

  if (action === BET_ACTION.FOLD) {
    a.folded = true;
    a.actedThisStreet = true;
    pushLog(next, `${a.name} FOLDS.`);
  } else if (action === BET_ACTION.CHECK) {
    // only legal if not facing a bet
    if (next.currentBet > a.committed) return w;
    a.actedThisStreet = true;
    pushLog(next, `${a.name} CHECKS.`);
  } else if (action === BET_ACTION.CALL) {
    const toCall = next.currentBet - a.committed;
    if (toCall <= 0) {
      // nothing to call -> treat as check
      a.actedThisStreet = true;
      pushLog(next, `${a.name} CHECKS (no bet to call).`);
    } else {
      if (a.coins < toCall) return w; // no partial calls / side pots in V2
      const pay = toCall;
      a.coins -= pay;
      a.committed += pay;
      a.totalCommitted += pay;
      next.pot += pay;
      a.actedThisStreet = true;
      pushLog(next, `${a.name} CALLS ${pay}. Pot = ${next.pot}.`);
    }
  } else if (action === BET_ACTION.RAISE) {
    if (next.raiseCountThisStreet >= 1) return w; // max one raise per street
    const toCall = Math.max(0, next.currentBet - a.committed);
    // Raise is exactly 2x the current pot. V2 has no partial all-in raises.
    const rake = 2 * next.pot;
    const pay = toCall + rake;
    if (pay <= 0 || a.coins < pay) return w;
    a.coins -= pay;
    a.committed += pay;
    a.totalCommitted += pay;
    next.pot += pay;
    next.currentBet = a.committed;
    next.lastRaiserId = a.id;
    next.raiseCountThisStreet += 1;
    a.actedThisStreet = true;
    // re-open action for others
    for (const s of next.seats) if (s.id !== a.id) s.actedThisStreet = false;
    pushLog(next, `${a.name} RAISES ${rake} (total ${pay}). Pot = ${next.pot}.`);
  } else {
    return w;
  }

  // Betting round closed?
  const liveUnfolded = activeSeats(next);
  const allActed = liveUnfolded.every((s) => s.actedThisStreet);
  const noUnmatchedBet = liveUnfolded.every((s) => s.committed === next.currentBet);

  if (liveUnfolded.length <= 1) {
    // everyone else folded -> hand ends immediately
    return settle(next);
  }
  if (allActed && noUnmatchedBet) {
    if (next.streetIndex === STREETS.length - 1 && next.lastRaiserId) {
      return startRiverBonus(next);
    }
    return advanceStreet(next);
  }
  return next;
}

/** A called river raise unlocks exactly one final swap for each live seat. */
function startRiverBonus(w) {
  const next = clone(w);
  next.phase = WAGER_PHASE.STREET_MOVE;
  next.moveKind = 'river_bonus';
  next.moveSeatIds = activeSeats(next).map((s) => s.id);
  next.movesThisStreet = 0;
  next.requiredMovesThisStreet = next.moveSeatIds.length;
  for (const s of next.seats) {
    s.committed = 0;
    s.actedThisStreet = false;
  }
  next.currentBet = 0;
  next.raiseCountThisStreet = 0;
  next.lastRaiserId = null;
  pushLog(next, 'River raise called. Final bonus swap round — one move each, then showdown.');
  return next;
}

/** End-of-betting: either go to next street or showdown. */
function advanceStreet(w) {
  const next = clone(w);
  // reset per-street committed display baseline is kept; just clear currentBet baseline
  next.streetIndex += 1;
  if (next.streetIndex >= STREETS.length) {
    next.phase = WAGER_PHASE.SHOWDOWN;
    pushLog(next, `Showdown. Pot = ${next.pot}.`);
    return showdown(next);
  }
  next.street = STREETS[next.streetIndex];
  next.phase = WAGER_PHASE.STREET_MOVE;
  next.moveKind = 'street';
  next.moveSeatIds = activeSeats(next).map((s) => s.id);
  next.movesThisStreet = 0;
  next.requiredMovesThisStreet = next.moveSeatIds.length;
  for (const s of next.seats) {
    s.committed = 0; // new street, fresh commit baseline
    s.actedThisStreet = false;
  }
  next.currentBet = 0;
  next.raiseCountThisStreet = 0;
  next.lastRaiserId = null;
  pushLog(next, `Street: ${next.street}. Make your move.`);
  return next;
}

/**
 * Auto-action for a seat that timed out: CHECK if facing no bet, else FOLD.
 * Never raises/increases exposure involuntarily.
 */
export function autoAct(w, actorId) {
  const actor = w.seats.find((s) => s.id === actorId);
  if (!actor) return w;
  if (w.phase !== WAGER_PHASE.BETTING || actor.folded || actor.actedThisStreet) return w;
  const facingBet = w.currentBet > actor.committed;
  return applyBet(w, actorId, facingBet ? BET_ACTION.FOLD : BET_ACTION.CHECK);
}

/**
 * End a hand when a player leaves or exceeds an authoritative match deadline.
 * Unlike a normal betting fold, a forfeit is valid during any active phase.
 */
export function forfeit(w, actorId, reason = 'forfeits') {
  if (!w || w.phase === WAGER_PHASE.COMPLETE || w.settled) return w;

  const actor = w.seats.find((seat) => seat.id === actorId);
  if (!actor || actor.folded) return w;

  const next = clone(w);
  const forfeitingSeat = next.seats.find((seat) => seat.id === actorId);
  forfeitingSeat.folded = true;
  forfeitingSeat.actedThisStreet = true;
  pushLog(next, `${forfeitingSeat.name} ${reason}.`);

  return activeSeats(next).length <= 1 ? settle(next) : next;
}

/**
 * Showdown: pot goes to highest score among non-folded seats; ties split.
 * `scores` is a map { seatId: score }.
 */
export function showdown(w, scores = {}) {
  const next = clone(w);
  const live = activeSeats(next);
  if (live.length === 0) {
    // all folded (shouldn't happen) — refund nothing, pot stays
    next.winnerIds = [];
  } else if (live.length === 1) {
    next.winnerIds = [live[0].id];
  } else {
    const seatScore = (s) => scores[s.id] != null ? scores[s.id] : (s.score || 0);
    let best = -Infinity;
    for (const s of live) best = Math.max(best, seatScore(s));
    next.winnerIds = live.filter((s) => seatScore(s) === best).map((s) => s.id);
  }
  return settle(next);
}

/** Award the pot to winners and mark complete. */
function settle(w) {
  if (w.settled) return w;
  const next = clone(w);
  const winners = next.winnerIds.length ? next.winnerIds : activeSeats(next).map((s) => s.id);
  next.winnerIds = winners; // persist so the UI can name the pot winner
  const share = winners.length ? Math.floor(next.pot / winners.length) : 0;
  for (const s of next.seats) {
    if (winners.includes(s.id)) s.coins += share;
  }
  next.settled = true;
  next.phase = WAGER_PHASE.COMPLETE;
  const names = winners.map((id) => seatName(next, id)).join(', ');
  pushLog(next, `Settled. Winners: ${names || 'none'}. Each +${share}. Pot distributed.`);
  return next;
}

export function seatName(w, id) {
  const s = w.seats.find((x) => x.id === id);
  return s ? s.name : id;
}

/** Convenience: who must act now (for UI/timer). */
export function currentActor(w) {
  if (w.phase === WAGER_PHASE.BETTING) return bettingActor(w);
  return null;
}

/** Is the hand over? */
export function isComplete(w) {
  return w.phase === WAGER_PHASE.COMPLETE;
}
