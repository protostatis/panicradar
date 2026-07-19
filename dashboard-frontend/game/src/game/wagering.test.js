import { describe, expect, it } from 'vitest';
import {
  BET_ACTION,
  WAGER_PHASE,
  applyBet,
  createWager,
  currentMoveActor,
  postAnte,
  recordStreetMove,
  showdown,
} from './wagering';

function newHand(startingCoins = 300) {
  return postAnte(createWager({
    startingCoins,
    players: [
      { id: 'human', name: 'Human', kind: 'human' },
      { id: 'computer', name: 'Computer', kind: 'computer' },
    ],
  }));
}

function finishMoves(wager, scores = {}) {
  let next = recordStreetMove(wager, 'human', scores);
  next = recordStreetMove(next, 'computer', scores);
  return next;
}

function checkThrough(wager) {
  let next = applyBet(wager, 'human', BET_ACTION.CHECK);
  next = applyBet(next, 'computer', BET_ACTION.CHECK);
  return next;
}

function reachRiverMoves(scores = {}) {
  let wager = newHand();
  wager = checkThrough(finishMoves(wager, scores));
  wager = checkThrough(finishMoves(wager, scores));
  return wager;
}

function reachRiverBetting(scores = {}) {
  return finishMoves(reachRiverMoves(scores), scores);
}

describe('wagering reducer', () => {
  it('uses persisted match scores to settle a standard river showdown', () => {
    let wager = reachRiverBetting({ human: 18, computer: 11 });
    wager = applyBet(wager, 'human', BET_ACTION.CHECK);
    wager = applyBet(wager, 'computer', BET_ACTION.CHECK);

    expect(wager.phase).toBe(WAGER_PHASE.COMPLETE);
    expect(wager.winnerIds).toEqual(['human']);
    expect(wager.seats.find((seat) => seat.id === 'human').score).toBe(18);
  });

  it('splits a tied pot without losing credits', () => {
    let wager = reachRiverBetting({ human: 12, computer: 12 });
    wager = applyBet(wager, 'human', BET_ACTION.CHECK);
    wager = applyBet(wager, 'computer', BET_ACTION.CHECK);

    expect(wager.winnerIds).toEqual(['human', 'computer']);
    expect(wager.seats.reduce((sum, seat) => sum + seat.coins, 0)).toBe(600);
  });

  it('settles a fold immediately in favor of the live seat', () => {
    let wager = finishMoves(newHand(), { human: 3, computer: 30 });
    wager = applyBet(wager, 'human', BET_ACTION.RAISE);
    wager = applyBet(wager, 'computer', BET_ACTION.FOLD);

    expect(wager.phase).toBe(WAGER_PHASE.COMPLETE);
    expect(wager.winnerIds).toEqual(['human']);
  });

  it('advances an earlier-street raise and call without a bonus round', () => {
    let wager = finishMoves(newHand());
    wager = applyBet(wager, 'human', BET_ACTION.RAISE);
    wager = applyBet(wager, 'computer', BET_ACTION.CALL);

    expect(wager.phase).toBe(WAGER_PHASE.STREET_MOVE);
    expect(wager.street).toBe('turn');
    expect(wager.moveKind).toBe('street');
  });

  it('unlocks one bonus swap each after a called river raise', () => {
    let wager = reachRiverBetting({ human: 10, computer: 20 });
    wager = applyBet(wager, 'human', BET_ACTION.RAISE);
    wager = applyBet(wager, 'computer', BET_ACTION.CALL);

    expect(wager.phase).toBe(WAGER_PHASE.STREET_MOVE);
    expect(wager.moveKind).toBe('river_bonus');
    expect(currentMoveActor(wager)?.id).toBe('human');
    expect(recordStreetMove(wager, 'computer', { human: 10, computer: 20 })).toBe(wager);

    wager = recordStreetMove(wager, 'human', { human: 25, computer: 20 });
    expect(currentMoveActor(wager)?.id).toBe('computer');
    wager = recordStreetMove(wager, 'computer', { human: 25, computer: 24 });

    expect(wager.phase).toBe(WAGER_PHASE.COMPLETE);
    expect(wager.winnerIds).toEqual(['human']);
  });

  it('rejects invalid and out-of-turn actions without mutating state', () => {
    const moving = newHand();
    expect(recordStreetMove(moving, 'computer')).toBe(moving);

    const betting = finishMoves(moving);
    expect(applyBet(betting, 'computer', BET_ACTION.CHECK)).toBe(betting);
    expect(applyBet(betting, 'human', BET_ACTION.CALL)).not.toBe(betting);
  });

  it('rejects unaffordable calls, raises, and antes', () => {
    let wager = finishMoves(newHand());
    wager = applyBet(wager, 'human', BET_ACTION.RAISE);
    const shortComputer = {
      ...wager,
      seats: wager.seats.map((seat) => seat.id === 'computer' ? { ...seat, coins: 1 } : seat),
    };
    expect(applyBet(shortComputer, 'computer', BET_ACTION.CALL)).toBe(shortComputer);

    const betting = finishMoves(newHand());
    const shortHuman = {
      ...betting,
      seats: betting.seats.map((seat) => seat.id === 'human' ? { ...seat, coins: 1 } : seat),
    };
    expect(applyBet(shortHuman, 'human', BET_ACTION.RAISE)).toBe(shortHuman);

    const cannotAnte = createWager({
      startingCoins: 5,
      players: [{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }],
    });
    expect(postAnte(cannotAnte)).toBe(cannotAnte);
  });

  it('conserves credits and cannot settle twice', () => {
    let wager = reachRiverBetting({ human: 30, computer: 5 });
    wager = applyBet(wager, 'human', BET_ACTION.CHECK);
    wager = applyBet(wager, 'computer', BET_ACTION.CHECK);
    const balances = wager.seats.map((seat) => seat.coins);

    expect(balances.reduce((sum, balance) => sum + balance, 0)).toBe(600);
    const afterShowdown = showdown(wager, { human: 999, computer: 0 });
    // settled wager must be unchanged — no re-award of the pot
    expect(afterShowdown.seats.map((seat) => seat.coins)).toEqual(balances);
  });
});
