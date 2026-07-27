/**
 * V2WagerRoom.test.js — server-authoritative V2 room tests (node:test).
 *
 * Run:  node --test server/V2WagerRoom.test.js
 */

import { describe, test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { V2WagerRoom } from './V2WagerRoom.js';
import { DemoCreditLedger } from './DemoCreditLedger.js';
import { WAGER_PHASE, currentActor, currentMoveActor, BET_ACTION } from '../src/game/wagering.js';

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function newRoom(ledger = new DemoCreditLedger()) {
  const room = new V2WagerRoom({ code: 'TEST01', ledger });
  testRooms.add(room);
  return room;
}

const testRooms = new Set();

afterEach(() => {
  for (const room of testRooms) room.close();
  testRooms.clear();
});

function mockWs() {
  return { readyState: 1, _sent: [], send(msg) { this._sent.push(msg); }, close() {} };
}

/** Find a valid move on the room's engine. */
function findValidMove(room) {
  const moves = room.engine.getValidMoves();
  assert.ok(moves.length > 0, 'engine should have at least one valid move');
  return moves[0];
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('DemoCreditLedger', () => {
  test('initial balance is 100 for any id', () => {
    const ledger = new DemoCreditLedger();
    assert.equal(ledger.getBalance('u1'), 100);
    assert.equal(ledger.getBalance('u2'), 100);
    assert.equal(ledger.getBalance('new-user'), 100);
  });

  test('canReserve returns true when enough balance', () => {
    const ledger = new DemoCreditLedger();
    assert.equal(ledger.canReserve('u1', 100), true);
    assert.equal(ledger.canReserve('u1', 101), false);
  });

  test('reserve deducts balance', () => {
    const ledger = new DemoCreditLedger();
    const r = ledger.reserve('alice', 50, 'match-1');
    assert.equal(r.ok, true);
    assert.equal(ledger.getBalance('alice'), 50);
  });

  test('reserve is idempotent for same player/match', () => {
    const ledger = new DemoCreditLedger();
    ledger.reserve('alice', 50, 'match-1');
    const r2 = ledger.reserve('alice', 50, 'match-1');
    assert.equal(r2.ok, true);
    assert.equal(ledger.getBalance('alice'), 50); // not deducted twice
  });

  test('refund returns credits', () => {
    const ledger = new DemoCreditLedger();
    ledger.reserve('alice', 50, 'match-1');
    const r = ledger.refund('match-1');
    assert.equal(r.ok, true);
    assert.equal(ledger.getBalance('alice'), 100);
  });

  test('settle distributes payouts', () => {
    const ledger = new DemoCreditLedger();
    ledger.reserve('alice', 100, 'm1');
    ledger.reserve('bob', 100, 'm1');
    const r = ledger.settle('m1', { alice: 150, bob: 50 });
    assert.equal(r.ok, true);
    assert.equal(ledger.getBalance('alice'), 150);
    assert.equal(ledger.getBalance('bob'), 50);
  });

  test('settle rejects duplicate settlement', () => {
    const ledger = new DemoCreditLedger();
    ledger.reserve('alice', 100, 'm1');
    ledger.reserve('bob', 100, 'm1');
    ledger.settle('m1', { alice: 100, bob: 100 });
    const r2 = ledger.settle('m1', { alice: 200, bob: 0 });
    assert.equal(r2.ok, false);
    assert.ok(r2.error.includes('already settled'));
  });

  test('refund rejects on already-settled escrow', () => {
    const ledger = new DemoCreditLedger();
    ledger.reserve('alice', 100, 'm1');
    ledger.reserve('bob', 100, 'm1');
    ledger.settle('m1', { alice: 100, bob: 100 });
    const r = ledger.refund('m1');
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('already settled'));
  });

  test('settle rejects on already-refunded escrow', () => {
    const ledger = new DemoCreditLedger();
    ledger.reserve('alice', 100, 'm1');
    ledger.reserve('bob', 100, 'm1');
    ledger.refund('m1');
    const r = ledger.settle('m1', { alice: 100, bob: 100 });
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('already refunded'));
  });

  test('ensurePlayable restores a broke account only when no escrow is active', () => {
    const ledger = new DemoCreditLedger();
    ledger.reserve('alice', 100, 'm1');
    ledger.settle('m1', { alice: 0 });
    assert.equal(ledger.ensurePlayable('alice', 10), 100);

    ledger.reserve('alice', 100, 'm2');
    assert.equal(ledger.ensurePlayable('alice', 10), 0);
  });
});

describe('V2WagerRoom — lifecycle', () => {
  test('starts in lobby', () => {
    const room = newRoom();
    assert.equal(room.lifecycle, 'lobby');
  });

  test('first join succeeds', () => {
    const room = newRoom();
    const r = room.join({ id: 'alice', name: 'Alice' });
    assert.equal(r.ok, true);
  });

  test('second distinct player auto-activates room', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    const r = room.join({ id: 'bob', name: 'Bob' });
    assert.equal(r.ok, true);
    assert.equal(room.lifecycle, 'active');
    assert.ok(room.wager);
    assert.equal(room.wager.phase, WAGER_PHASE.STREET_MOVE);
  });

  test('third join rejected (room full)', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    const r = room.join({ id: 'charlie', name: 'Charlie' });
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('full'));
  });

  test('rejoin is idempotent', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    const r = room.join({ id: 'alice', name: 'Alice' });
    assert.equal(r.ok, true);
  });

  test('auto-activation reserves 100 from each player', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    assert.equal(room.lifecycle, 'active');
    assert.equal(ledger.getBalance('alice'), 0);
    assert.equal(ledger.getBalance('bob'), 0);
  });

  test('repeat match uses the lower returned balance instead of stranding a loser', () => {
    const ledger = new DemoCreditLedger();
    ledger.reserve('alice', 100, 'previous');
    ledger.reserve('bob', 100, 'previous');
    ledger.settle('previous', { alice: 110, bob: 90 });

    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    assert.equal(room.lifecycle, 'active');
    assert.equal(room.buyIn, 90);
    assert.equal(room.wager.seats[0].coins, 80);
    assert.equal(room.wager.seats[1].coins, 80);
  });

  test('auto-activation fails if player lacks credits', () => {
    const ledger = new DemoCreditLedger();
    ledger.reserve('bob', 100, 'drain');
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    const r = room.join({ id: 'bob', name: 'Bob' });
    assert.equal(r.ok, false);
    assert.match(r.error, /insufficient credits/i);
    assert.equal(room.lifecycle, 'lobby');
    assert.equal(room._seats.length, 1);
  });
});

describe('V2WagerRoom — tryMove', () => {
  test('rejects stale revision', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    const r = room.tryMove('alice', 0, 1, 999);
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('Stale revision'));
  });

  test('rejects move when not in STREET_MOVE phase', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    room.wager.phase = WAGER_PHASE.BETTING;
    const r = room.tryMove('alice', 0, 1, room.revision);
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('STREET_MOVE'));
    room.wager.phase = WAGER_PHASE.STREET_MOVE;
  });

  test('rejects move from wrong player', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    const actor = currentMoveActor(room.wager);
    const other = room._seats.find((s) => s.id !== actor.id);
    const [i, j] = findValidMove(room);
    const r = room.tryMove(other.id, i, j, room.revision);
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('Not your turn'));
  });

  test('valid move succeeds and updates score', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    const actor = currentMoveActor(room.wager);
    const [i, j] = findValidMove(room);
    const rev = room.revision;
    const r = room.tryMove(actor.id, i, j, rev);
    assert.equal(r.ok, true);
    assert.ok(room.scores[actor.id] > 0);
    assert.ok(room.revision > rev);

    const snap = room.snapshotFor(actor.id);
    assert.equal(snap.presentation.kind, 'cascade');
    assert.equal(snap.presentation.baseRevision, rev);
    assert.equal(snap.presentation.revision, room.revision);
    assert.deepEqual(snap.presentation.swap, [i, j]);
    assert.ok(snap.presentation.steps.length > 0);
    assert.deepEqual(snap.presentation.steps.at(-1).afterCells, snap.cells);
  });

  test('rejects invalid swap', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    const actor = currentMoveActor(room.wager);
    const rev = room.revision;
    const r = room.tryMove(actor.id, 0, 63, rev);
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('Invalid swap'));
  });
});

describe('V2WagerRoom — tryBet', () => {
  test('rejects stale revision', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    const r = room.tryBet('alice', BET_ACTION.CHECK, 999);
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('Stale revision'));
  });

  test('rejects bet when not in BETTING phase', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    const r = room.tryBet('alice', BET_ACTION.CHECK, room.revision);
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('BETTING'));
  });

  test('rejects bet from wrong player', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    const actors = [...room._seats];
    for (const s of actors) {
      const [i, j] = findValidMove(room);
      room.tryMove(s.id, i, j, room.revision);
    }
    assert.equal(room.wager.phase, WAGER_PHASE.BETTING);

    const actor = currentActor(room.wager);
    const other = room._seats.find((s) => s.id !== actor.id);
    const r = room.tryBet(other.id, BET_ACTION.CHECK, room.revision);
    assert.equal(r.ok, false);
    assert.ok(r.error.includes('Not your turn'));

    room._clearDeadline();
  });

  test('no-op actions rejected', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    for (const s of room._seats) {
      const [i, j] = findValidMove(room);
      room.tryMove(s.id, i, j, room.revision);
    }
    assert.equal(room.wager.phase, WAGER_PHASE.BETTING);

    const actor = currentActor(room.wager);
    const rev = room.revision;
    const r = room.tryBet(actor.id, 'nonsense', rev);
    assert.equal(r.ok, false);
    assert.equal(room.revision, rev);

    room._clearDeadline();
  });
});

describe('V2WagerRoom — snapshot + broadcast', () => {
  test('snapshotFor returns correct shape', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    const snap = room.snapshotFor('alice');
    assert.equal(snap.type, 'V2_SNAPSHOT');
    assert.equal(snap.code, undefined);
    assert.equal(snap.lifecycle, 'active');
    assert.equal(typeof snap.revision, 'number');
    assert.ok(Array.isArray(snap.cells));
    assert.equal(snap.cells.length, 64);
    assert.ok(snap.cells[0].type !== undefined);
    assert.ok(snap.cells[0].id !== undefined);
    assert.ok(snap.wager);
    assert.ok(Array.isArray(snap.players));
    assert.equal(snap.players.length, 2);
    assert.equal(snap.self.id, 'alice');
    assert.equal(snap.self.seat, 0);
    assert.ok(snap.activeSeatId);
  });

  test('broadcast sends to all connected sockets', () => {
    const room = newRoom();
    const ws1 = mockWs();
    const ws2 = mockWs();

    room.join({ id: 'alice', name: 'Alice' });
    room.addSocket(ws1, 'alice');
    room.join({ id: 'bob', name: 'Bob' });
    room.addSocket(ws2, 'bob');

    room.broadcast();
    assert.equal(ws1._sent.length, 1);
    assert.equal(ws2._sent.length, 1);

    const snap = JSON.parse(ws1._sent[0]);
    assert.equal(snap.type, 'V2_SNAPSHOT');
    assert.equal(snap.self.id, 'alice');

    const snap2 = JSON.parse(ws2._sent[0]);
    assert.equal(snap2.self.id, 'bob');
  });
});

describe('V2WagerRoom — full-flow', () => {
  test('complete hand: all streets check-check, final showdown settles ledger once', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    assert.equal(room.lifecycle, 'active');
    const seats = [...room._seats];

    function doStreet() {
      for (const s of seats) {
        const [i, j] = findValidMove(room);
        const r = room.tryMove(s.id, i, j, room.revision);
        assert.equal(r.ok, true, `move should succeed for ${s.id}`);
      }
      assert.equal(room.wager.phase, WAGER_PHASE.BETTING, 'should enter betting');
      for (const s of seats) {
        const r = room.tryBet(s.id, BET_ACTION.CHECK, room.revision);
        assert.equal(r.ok, true, `check should succeed for ${s.id}`);
      }
    }

    doStreet();
    assert.equal(room.wager.street, 'turn', 'should advance to turn');

    doStreet();
    assert.equal(room.wager.street, 'river', 'should advance to river');

    for (const s of seats) {
      const [i, j] = findValidMove(room);
      const r = room.tryMove(s.id, i, j, room.revision);
      assert.equal(r.ok, true, `river move should succeed for ${s.id}`);
    }
    assert.equal(room.wager.phase, WAGER_PHASE.BETTING, 'river betting');

    for (const s of seats) {
      const r = room.tryBet(s.id, BET_ACTION.CHECK, room.revision);
      assert.equal(r.ok, true, `river check should succeed for ${s.id}`);
    }

    assert.equal(room.wager.phase, WAGER_PHASE.COMPLETE);
    assert.equal(room.lifecycle, 'complete');
    assert.ok(room.result);
    assert.ok(Array.isArray(room.result.winnerIds));
    assert.ok(room.result.payouts);

    const totalPayout = Object.values(room.result.payouts).reduce((a, b) => a + b, 0);
    assert.ok(totalPayout >= 198, `total payout ${totalPayout} should be near 200`);
    assert.ok(totalPayout <= 200);

    room._settleLedger(); // should be no-op
    assert.equal(ledger.getBalance('alice') + ledger.getBalance('bob'), totalPayout);
  });

  test('river raise + call unlocks bonus move state, second bonus move completes', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    const seats = [...room._seats];

    for (let street = 0; street < 2; street++) {
      for (const s of seats) {
        const [i, j] = findValidMove(room);
        room.tryMove(s.id, i, j, room.revision);
      }
      for (const s of seats) {
        room.tryBet(s.id, BET_ACTION.CHECK, room.revision);
      }
    }
    assert.equal(room.wager.street, 'river');

    for (const s of seats) {
      const [i, j] = findValidMove(room);
      room.tryMove(s.id, i, j, room.revision);
    }
    assert.equal(room.wager.phase, WAGER_PHASE.BETTING, 'river betting');

    const bettor = currentActor(room.wager);
    const revBeforeRaise = room.revision;
    const r = room.tryBet(bettor.id, BET_ACTION.RAISE, revBeforeRaise);
    assert.equal(r.ok, true, 'raise should succeed');

    const caller = currentActor(room.wager);
    assert.ok(caller, 'should have an actor to call');
    assert.notEqual(caller.id, bettor.id, 'caller should be the other player');
    const r2 = room.tryBet(caller.id, BET_ACTION.CALL, room.revision);
    assert.equal(r2.ok, true, 'call should succeed');

    assert.equal(room.wager.phase, WAGER_PHASE.STREET_MOVE);
    assert.equal(room.wager.moveKind, 'river_bonus');

    const bonusActor1 = currentMoveActor(room.wager);
    const [i1, j1] = findValidMove(room);
    room.tryMove(bonusActor1.id, i1, j1, room.revision);

    assert.equal(room.wager.phase, WAGER_PHASE.STREET_MOVE);
    const bonusActor2 = currentMoveActor(room.wager);
    assert.notEqual(bonusActor2.id, bonusActor1.id);

    const [i2, j2] = findValidMove(room);
    const r3 = room.tryMove(bonusActor2.id, i2, j2, room.revision);
    assert.equal(r3.ok, true);

    assert.equal(room.wager.phase, WAGER_PHASE.COMPLETE);
    assert.equal(room.lifecycle, 'complete');
    assert.ok(room.result);
    assert.ok(room.result.winnerIds.length > 0);
  });
});

describe('V2WagerRoom — timeout behaviour', () => {
  test('_onDeadline forfeits the current move actor and settles once', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    assert.equal(room.wager.phase, WAGER_PHASE.STREET_MOVE);
    assert.ok(room.deadline, 'swap turn should have a deadline');

    const actor = currentMoveActor(room.wager);
    const capturedRev = room.revision;
    room._onDeadline(capturedRev, room.code);

    assert.ok(room.revision > capturedRev, 'timeout should advance the revision');
    assert.equal(room.wager.phase, WAGER_PHASE.COMPLETE);
    assert.equal(room.lifecycle, 'complete');
    assert.equal(room.deadline, null);
    assert.equal(room.wager.seats.find((seat) => seat.id === actor.id).folded, true);
    assert.deepEqual(room.result.winnerIds, [room._seats.find((seat) => seat.id !== actor.id).id]);
    assert.equal(ledger.getBalance('alice') + ledger.getBalance('bob'), 200);
  });

  test('_onDeadline also forfeits during betting', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    for (const seat of room._seats) {
      const [i, j] = findValidMove(room);
      room.tryMove(seat.id, i, j, room.revision);
    }
    const actor = currentActor(room.wager);
    room._onDeadline(room.revision, room.code);

    assert.equal(room.lifecycle, 'complete');
    assert.equal(room.wager.seats.find((seat) => seat.id === actor.id).folded, true);
  });

  test('_onDeadline with stale revision is a no-op', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    const seats = [...room._seats];
    for (const s of seats) {
      const [i, j] = findValidMove(room);
      room.tryMove(s.id, i, j, room.revision);
    }
    assert.equal(room.wager.phase, WAGER_PHASE.BETTING);

    const capturedRev = room.revision;
    const actor = currentActor(room.wager);
    room.tryBet(actor.id, BET_ACTION.CHECK, room.revision);
    const newRev = room.revision;
    assert.ok(newRev > capturedRev);

    const snapshotWager = room.wager;
    room._onDeadline(capturedRev, room.code);
    assert.equal(room.wager, snapshotWager, 'wager should be unchanged');
    assert.equal(room.revision, newRev, 'revision unchanged');

    room._clearDeadline();
  });
});

describe('V2WagerRoom — close()', () => {
  test('close refunds unreserved escrow and marks complete', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    assert.equal(room.lifecycle, 'active');

    room.close();

    assert.equal(room.lifecycle, 'complete');
    assert.equal(ledger.getBalance('alice'), 100);
    assert.equal(ledger.getBalance('bob'), 100);
  });

  test('close after settlement does not double-refund', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    const seats = [...room._seats];
    for (let street = 0; street < 3; street++) {
      for (const s of seats) {
        const [i, j] = findValidMove(room);
        room.tryMove(s.id, i, j, room.revision);
      }
      for (const s of seats) {
        room.tryBet(s.id, BET_ACTION.CHECK, room.revision);
      }
    }
    assert.equal(room.lifecycle, 'complete');

    const balBefore = ledger.getBalance('alice');
    room.close();
    assert.equal(ledger.getBalance('alice'), balBefore);
  });
});

describe('V2WagerRoom — fold settles immediately', () => {
  test('fold ends hand and awards pot to non-folding player', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    const seats = [...room._seats];

    for (const s of seats) {
      const [i, j] = findValidMove(room);
      room.tryMove(s.id, i, j, room.revision);
    }
    assert.equal(room.wager.phase, WAGER_PHASE.BETTING);

    const actor = currentActor(room.wager);
    const r = room.tryBet(actor.id, BET_ACTION.FOLD, room.revision);
    assert.equal(r.ok, true);

    assert.equal(room.wager.phase, WAGER_PHASE.COMPLETE);
    assert.equal(room.lifecycle, 'complete');
    const nonFolder = seats.find((s) => s.id !== actor.id);
    assert.ok(room.result.winnerIds.includes(nonFolder.id));
  });

  test('forfeit settles immediately during a move phase and is idempotent', () => {
    const ledger = new DemoCreditLedger();
    const room = newRoom(ledger);
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    const first = room.forfeit('alice', 'disconnects and forfeits');
    const balances = [ledger.getBalance('alice'), ledger.getBalance('bob')];
    const second = room.forfeit('alice', 'disconnects and forfeits');

    assert.equal(first.ok, true);
    assert.equal(second.ok, false);
    assert.equal(room.lifecycle, 'complete');
    assert.deepEqual(room.result.winnerIds, ['bob']);
    assert.deepEqual([ledger.getBalance('alice'), ledger.getBalance('bob')], balances);
  });
});

describe('V2WagerRoom — rematch consent', () => {
  test('requires both seated players to consent after a settled hand', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });
    room.lifecycle = 'complete';
    room._settled = true;

    const first = room.requestRematch('alice');
    assert.deepEqual(first, { ok: true, agreed: false });
    assert.deepEqual(room.snapshotFor('bob').rematch, { requestedSeatIds: ['alice'] });

    const second = room.requestRematch('bob');
    assert.deepEqual(second, { ok: true, agreed: true });
  });

  test('rejects rematch consent before settlement and from spectators', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    assert.match(room.requestRematch('alice').error, /settled hand/i);
    room.lifecycle = 'complete';
    room._settled = true;
    assert.match(room.requestRematch('charlie').error, /match players/i);
  });
});

describe('V2WagerRoom — rematch revision gap', () => {
  test('new rematch room starts with revision 1, below the settled room\'s final revision', () => {
    const ledger = new DemoCreditLedger();

    // Play a single street (move+bet for each player) to build revision history
    const oldRoom = newRoom(ledger);
    oldRoom.join({ id: 'alice', name: 'Alice' });
    oldRoom.join({ id: 'bob', name: 'Bob' });

    // Revision is 1 after activation. Play one full street.
    const seats = [...oldRoom._seats];
    for (const s of seats) {
      const [i, j] = findValidMove(oldRoom);
      const r = oldRoom.tryMove(s.id, i, j, oldRoom.revision);
      assert.equal(r.ok, true, `move should succeed for ${s.id}`);
    }
    assert.equal(oldRoom.wager.phase, WAGER_PHASE.BETTING, 'should enter betting');
    for (const s of seats) {
      const r = oldRoom.tryBet(s.id, BET_ACTION.CHECK, oldRoom.revision);
      assert.equal(r.ok, true, `check should succeed for ${s.id}`);
    }

    const oldFinalRevision = oldRoom.revision;
    assert.ok(oldFinalRevision >= 5,
      `Expected room revision >= 5 after one street, got ${oldFinalRevision}`);

    // Simulate startV2Rematch: close old room (refunds escrow) and create a new one
    oldRoom.close();

    const rematchRoom = new V2WagerRoom({ code: 'REMATCH01', ledger });
    testRooms.add(rematchRoom);
    rematchRoom.join({ id: 'alice', name: 'Alice' });
    rematchRoom.join({ id: 'bob', name: 'Bob' });

    // After auto-activation, revision is 1 (constructor 0 + _tryActivate++)
    assert.equal(rematchRoom.lifecycle, 'active');
    assert.ok(rematchRoom.revision < oldFinalRevision,
      `New room revision (${rematchRoom.revision}) should be < old room revision (${oldFinalRevision})`);
    assert.equal(rematchRoom.revision, 1,
      'New room should start at revision 1 after activation');
  });
});

describe('V2WagerRoom — dead-board handling', () => {
  test('_ensurePlayable returns true after reshuffle on dead board', () => {
    const room = newRoom();
    room.join({ id: 'alice', name: 'Alice' });
    room.join({ id: 'bob', name: 'Bob' });

    // Play a move and verify board is still playable
    const actor = currentMoveActor(room.wager);
    const [i, j] = findValidMove(room);
    room.tryMove(actor.id, i, j, room.revision);
    assert.ok(room.engine.hasValidMoves());
  });
});
