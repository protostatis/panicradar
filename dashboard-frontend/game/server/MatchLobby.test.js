import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { MatchLobby } from './MatchLobby.js';

function mockWs() {
  return { readyState: 1, sent: [] };
}

function messages(ws, type) {
  return ws.sent.map((raw) => JSON.parse(raw)).filter((msg) => msg.type === type);
}

function createLobby(onMatchAccepted = () => ({ ok: true })) {
  return new MatchLobby({
    send: (ws, message) => {
      if (ws.readyState === 1) ws.sent.push(JSON.stringify(message));
    },
    onMatchAccepted,
    requestTtlMs: 60_000,
  });
}

function createLimitedLobby(maxPendingRequests) {
  return new MatchLobby({
    send: (ws, message) => {
      if (ws.readyState === 1) ws.sent.push(JSON.stringify(message));
    },
    onMatchAccepted: () => ({ ok: true }),
    requestTtlMs: 60_000,
    maxPendingRequests,
  });
}

const guest = { id: 'guest_A', name: 'Guest A1B2', authType: 'guest' };
const signed = { id: 'guest_B', name: 'Blake', authType: 'guest' };
const third = { id: 'guest_C', name: 'Guest C3D4', authType: 'guest' };

describe('MatchLobby', () => {
  test('publishes online guest players to every lobby socket', () => {
    const lobby = createLobby();
    const guestSocket = mockWs();
    const signedSocket = mockWs();

    lobby.attach(guestSocket, guest);
    lobby.attach(signedSocket, signed);

    const snapshot = messages(guestSocket, 'LOBBY_SNAPSHOT').at(-1);
    assert.equal(snapshot.self.userId, guest.id);
    assert.deepEqual(snapshot.players, [
      { userId: signed.id, name: signed.name, authType: 'guest', status: 'available' },
      { userId: guest.id, name: guest.name, authType: 'guest', status: 'available' },
    ]);
  });

  test('creates a match only after the target accepts a challenge', () => {
    const accepted = [];
    const lobby = createLobby((players) => {
      accepted.push(players);
      return { ok: true };
    });
    const guestSocket = mockWs();
    const signedSocket = mockWs();
    lobby.attach(guestSocket, guest);
    lobby.attach(signedSocket, signed);

    const request = lobby.request(guest.id, signed.id);
    assert.equal(request.ok, true);
    assert.equal(accepted.length, 0);
    assert.equal(messages(signedSocket, 'MATCH_REQUEST_RECEIVED').length, 1);

    const response = lobby.respond(signed.id, request.requestId, true);
    assert.equal(response.ok, true);
    assert.deepEqual(accepted, [{ from: guest, target: signed }]);
    assert.equal(messages(guestSocket, 'MATCH_STARTED').length, 1);
    assert.equal(messages(signedSocket, 'MATCH_STARTED').length, 1);

    const snapshot = messages(guestSocket, 'LOBBY_SNAPSHOT').at(-1);
    assert.equal(snapshot.players.find((player) => player.userId === guest.id).status, 'in_match');
    assert.equal(snapshot.players.find((player) => player.userId === signed.id).status, 'in_match');
  });

  test('rejects self-challenges and requests to a busy player', () => {
    const lobby = createLobby();
    const a = mockWs();
    const b = mockWs();
    const c = mockWs();
    lobby.attach(a, guest);
    lobby.attach(b, signed);
    lobby.attach(c, third);

    assert.match(lobby.request(guest.id, guest.id).error, /yourself/i);
    assert.equal(lobby.request(guest.id, signed.id).ok, true);
    assert.match(lobby.request(third.id, signed.id).error, /not available/i);
  });

  test('caps globally pending challenges', () => {
    const lobby = createLimitedLobby(1);
    const sockets = [mockWs(), mockWs(), mockWs(), mockWs()];
    const players = [guest, signed, third, { id: 'guest_D', name: 'Guest D5E6', authType: 'guest' }];
    players.forEach((player, index) => lobby.attach(sockets[index], player));

    assert.equal(lobby.request(guest.id, signed.id).ok, true);
    assert.match(lobby.request(third.id, players[3].id).error, /queue is full/i);
  });

  test('removes disconnected players and cancels their pending challenge', () => {
    const lobby = createLobby();
    const guestSocket = mockWs();
    const signedSocket = mockWs();
    lobby.attach(guestSocket, guest);
    lobby.attach(signedSocket, signed);
    const request = lobby.request(guest.id, signed.id);

    lobby.detach(guestSocket, guest.id);

    const cancelled = messages(signedSocket, 'MATCH_REQUEST_CANCELLED').at(-1);
    assert.equal(cancelled.requestId, request.requestId);
    const snapshot = messages(signedSocket, 'LOBBY_SNAPSHOT').at(-1);
    assert.deepEqual(snapshot.players, [
      { userId: signed.id, name: signed.name, authType: 'guest', status: 'available' },
    ]);
  });
});
