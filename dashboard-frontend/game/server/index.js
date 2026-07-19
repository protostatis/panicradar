/**
 * index.js — PanicRadar BlockCoined authoritative V2 PvP WebSocket server.
 *
 * Production-hardened, guest-only:
 *  - HTTP server: GET /health JSON 200; exact WS upgrade /game/ws; other HTTP 404.
 *  - ws maxPayload ~16KB, perMessageDeflate false.
 *  - Strict origin allowlist from ALLOWED_ORIGINS; fail closed in production.
 *  - Trust X-Real-IP only as the Nginx ingress for per-IP caps.
 *  - Versioned client handshake (protocolVersion 1 in IDENTIFY_GUEST).
 *  - Message validation: non-null plain objects, text only, known type,
 *    bounded strings/integers. Commands accept intent only.
 *  - Global caps (connections, rooms/pending challenges), per-IP connection cap,
 *    per-socket message token bucket, challenge throttle/TTL, bounded maps.
 *  - Heartbeat ping/pong; terminate stale/slow clients.
 *  - Graceful SIGTERM/SIGINT stops upgrades and avoids disconnect forfeits.
 *  - Disconnect: before active match cancel challenges/no credits;
 *    during active match immediate atomic forfeit/settle to connected opponent;
 *    completed/rematch screen no extra settlement.
 *  - Single-process/in-memory demo state. UI/docs disclose restart/reset.
 */

import { createServer } from 'http';
import { WebSocketServer } from 'ws';
import { randomBytes } from 'crypto';
import { DemoCreditLedger } from './DemoCreditLedger.js';
import { MatchLobby } from './MatchLobby.js';
import { V2WagerRoom } from './V2WagerRoom.js';

// ---- Configuration ----

const PORT = process.env.PORT || 8080;
const PROTOCOL_VERSION = 1;
const MAX_PAYLOAD = 16384; // 16 KB
const MAX_CONNECTIONS = 200;
const MAX_ROOMS = 100;
const MAX_PENDING_CHALLENGES = 100;
const PER_IP_MAX = 10;
const HEARTBEAT_INTERVAL_MS = 25_000;
const BURST_LIMIT = 60; // messages per window
const WINDOW_MS = 1000;
const CHALLENGE_COOLDOWN_MS = 2_000;
const MAX_BUFFERED_BYTES = 256 * 1024;

// Allowed origins for production. Must be set explicitly.
const ALLOWED_ORIGINS = process.env.ALLOWED_ORIGINS
  ? process.env.ALLOWED_ORIGINS.split(',').map((s) => s.trim()).filter(Boolean)
  : (process.env.NODE_ENV === 'production'
    ? [] // fail closed in production if not set
    : ['http://localhost:5174', 'http://localhost:5173', 'http://localhost:3000']);

if (process.env.NODE_ENV === 'production' && ALLOWED_ORIGINS.length === 0) {
  throw new Error('ALLOWED_ORIGINS must contain at least one origin in production');
}

// ---- Global state ----

const v2Rooms = new Map(); // Map<string, V2WagerRoom>
const v2Credits = new DemoCreditLedger();
/** @type {Map<import('ws').WebSocket, {player:object|null, v2Room:V2WagerRoom|null, ip:string, tokenWindow:{tokens:number, resetAt:number}}>} */
const clients = new Map();
/** @type {Map<string, number>} IP -> connection count */
const ipCounts = new Map();

const GUEST_ADJECTIVES = [
  'Amber', 'Brisk', 'Cobalt', 'Copper', 'Daring', 'Ember', 'Fable', 'Golden',
  'Harbor', 'Indigo', 'Jolly', 'Kindle', 'Lucky', 'Mellow', 'Nimble', 'Opal',
  'Poppy', 'Quill', 'Rogue', 'Solar', 'Tidy', 'Velvet', 'Witty', 'Zephyr',
];
const GUEST_CREATURES = [
  'Badger', 'Comet', 'Falcon', 'Fox', 'Gecko', 'Heron', 'Kestrel', 'Lynx',
  'Mantis', 'Marten', 'Otter', 'Panda', 'Puffin', 'Raven', 'Salamander', 'Seal',
  'Sparrow', 'Tern', 'Tiger', 'Viper', 'Walrus', 'Wolf', 'Wren', 'Yak',
];

// ---- Helpers ----

function newMatchId() {
  return `match_${randomBytes(12).toString('base64url')}`;
}

function send(ws, obj) {
  if (ws.readyState !== 1) return false;
  const payload = JSON.stringify(obj);
  const bufferedAmount = Number.isFinite(ws.bufferedAmount) ? ws.bufferedAmount : 0;
  if (bufferedAmount + Buffer.byteLength(payload, 'utf8') > MAX_BUFFERED_BYTES) {
    try { ws.terminate(); } catch { /* ignore */ }
    return false;
  }
  ws.send(payload);
  return true;
}

function newGuestName() {
  const adjective = GUEST_ADJECTIVES[Math.floor(Math.random() * GUEST_ADJECTIVES.length)];
  const creature = GUEST_CREATURES[Math.floor(Math.random() * GUEST_CREATURES.length)];
  const name = `${adjective} ${creature}`;
  const isTaken = [...matchLobby.players.values()].some((record) => record.player.name === name);
  return isTaken ? `${name} ${randomBytes(1).toString('hex').toUpperCase()}` : name;
}

function newGuestPlayer() {
  return {
    id: `guest_${randomBytes(12).toString('base64url')}`,
    name: newGuestName(),
    authType: 'guest',
  };
}

function identityMessage(player) {
  return {
    type: 'IDENTITY_OK',
    self: {
      userId: player.id,
      name: player.name,
      authType: player.authType,
    },
  };
}

// ---- Message validation ----

const KNOWN_TYPES = new Set([
  'IDENTIFY_GUEST', 'MATCH_REQUEST', 'MATCH_RESPONSE', 'MATCH_CANCEL',
  'LEAVE_V2_MATCH', 'REMATCH_REQUEST', 'V2_MOVE', 'V2_BET',
]);

function validateMessage(msg) {
  if (!msg || typeof msg !== 'object' || Array.isArray(msg)) return false;
  if (typeof msg.type !== 'string') return false;
  if (!KNOWN_TYPES.has(msg.type)) return false;
  return true;
}

/** Rate-limit per-socket: token bucket with burst. */
function checkRateLimit(meta) {
  const now = Date.now();
  const w = meta.tokenWindow;
  if (now > w.resetAt) {
    w.tokens = BURST_LIMIT;
    w.resetAt = now + WINDOW_MS;
  }
  if (w.tokens <= 0) return false;
  w.tokens--;
  return true;
}

// ---- Room helpers ----

function endV2Match(room, message) {
  const playerIds = room._seats.map((seat) => seat.id);
  for (const meta of clients.values()) {
    if (meta.v2Room === room) meta.v2Room = null;
  }
  room.close();
  v2Rooms.delete(room.code);
  matchLobby.endMatch(playerIds, message);
}

function leaveCurrentV2Match(ws, message = 'Opponent left the match') {
  const meta = clients.get(ws);
  if (!meta?.v2Room) return;

  const room = meta.v2Room;
  const playerId = meta.player?.id;

  room.removeSocket(ws);
  meta.v2Room = null;

  // Determine disconnect policy after removing this socket. A player with
  // another attached socket remains connected and does not forfeit.
  if (room.lifecycle === 'active') {
    if (playerId && !room._isConnected(playerId)) {
      room.forfeit(playerId, 'disconnects and forfeits');
      endV2Match(room, message);
    } else {
      room.broadcast();
    }
  } else if (room.lifecycle === 'lobby') {
    // Before active match: cancel challenges, no credits affected
    if (playerId && !room._isConnected(playerId)) {
      endV2Match(room, `${meta.player?.name || 'Player'} left before the match started`);
    } else {
      room.broadcast();
    }
  } else {
    // Leaving a completed/rematch screen releases the room and both players.
    if (playerId && !room._isConnected(playerId)) {
      endV2Match(room, message);
    } else {
      room.broadcast();
    }
  }
}

function startV2Match({ from, target }) {
  if (v2Rooms.size >= MAX_ROOMS) return { ok: false, error: 'Server is full — try again later' };

  const room = new V2WagerRoom({ code: newMatchId(), ledger: v2Credits, send });
  const first = room.join(from);
  if (!first.ok) return first;
  const second = room.join(target);
  if (!second.ok) {
    room.close();
    return second;
  }

  const playerIds = new Set([from.id, target.id]);
  for (const [ws, meta] of clients) {
    if (!meta.player || !playerIds.has(meta.player.id)) continue;
    room.addSocket(ws, meta.player.id);
    meta.v2Room = room;
  }

  v2Rooms.set(room.code, room);
  room.broadcast();
  console.log(`[v2 match] ${from.name} vs ${target.name}`);
  return { ok: true };
}

function startV2Rematch(room) {
  if (v2Rooms.size >= MAX_ROOMS) return { ok: false, error: 'Server is full — try again later' };

  const players = room._seats.map((seat) => ({ id: seat.id, name: seat.name, kind: 'human' }));
  const rematch = new V2WagerRoom({ code: newMatchId(), ledger: v2Credits, send });
  for (const player of players) {
    const joined = rematch.join(player);
    if (!joined.ok) {
      rematch.close();
      return joined;
    }
  }

  const matchSockets = [];
  for (const [ws, meta] of clients) {
    if (meta.v2Room === room) matchSockets.push([ws, meta]);
  }

  room.close();
  v2Rooms.delete(room.code);
  for (const [ws, meta] of matchSockets) {
    rematch.addSocket(ws, meta.player.id);
    meta.v2Room = rematch;
    send(ws, { type: 'REMATCH_STARTED' });
  }

  v2Rooms.set(rematch.code, rematch);
  rematch.broadcast();
  console.log(`[v2 rematch] ${players.map((player) => player.name).join(' vs ')}`);
  return { ok: true };
}

// ---- Lobby ----

const matchLobby = new MatchLobby({
  send,
  onMatchAccepted: startV2Match,
  maxPendingRequests: MAX_PENDING_CHALLENGES,
});

// ---- Identity ----

function identifyGuest(ws) {
  const meta = clients.get(ws);
  if (!meta) return null;
  if (!meta.player) {
    meta.player = newGuestPlayer();
    send(ws, identityMessage(meta.player));
    matchLobby.attach(ws, meta.player);
  } else {
    send(ws, identityMessage(meta.player));
  }
  return meta;
}

function requireV2Identity(ws) {
  const meta = clients.get(ws);
  if (!meta?.player) {
    send(ws, { type: 'ERROR', message: 'Connecting to the match lobby failed' });
    return null;
  }
  return meta;
}

// ---- Origin check ----

function checkOrigin(origin) {
  if (!origin || ALLOWED_ORIGINS.length === 0) return false;
  return ALLOWED_ORIGINS.includes(origin);
}

// ---- Graceful shutdown ----

let shuttingDown = false;

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log('[server] Graceful shutdown — stopping upgrades and cleaning up...');

  // Close all rooms (refund unreserved escrows)
  for (const room of v2Rooms.values()) room.close();
  v2Rooms.clear();

  // Close all client connections without triggering disconnect forfeits
  for (const [ws] of clients) {
    try { ws.close(1001, 'Server restarting'); } catch { /* ignore */ }
  }
  clients.clear();
  ipCounts.clear();

  wss.close(() => {
    httpServer.close(() => {
      console.log('[server] Shutdown complete.');
      process.exit(0);
    });
  });

  // Force exit after 10s
  setTimeout(() => process.exit(1), 10_000);
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

// ---- HTTP + WebSocket server ----

const httpServer = createServer((req, res) => {
  // Health check
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      status: 'ok',
      version: PROTOCOL_VERSION,
      clients: clients.size,
      rooms: v2Rooms.size,
    }));
    return;
  }

  // All other HTTP: 404
  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('Not Found');
});

const wss = new WebSocketServer({
  noServer: true,
  maxPayload: MAX_PAYLOAD,
  perMessageDeflate: false,
});

// Handle upgrade with origin check
httpServer.on('upgrade', (request, socket, head) => {
  // Only /game/ws path
  if (request.url !== '/game/ws') {
    socket.destroy();
    return;
  }

  // Check origin in production
  const origin = request.headers.origin;
  if (!checkOrigin(origin)) {
    socket.destroy();
    console.warn(`[server] Rejected connection from origin: ${origin}`);
    return;
  }

  // Read client IP from X-Real-IP (Nginx ingress)
  const ip = (request.headers['x-real-ip'] || socket.remoteAddress || 'unknown').toString();

  // Per-IP connection cap
  const ipCount = ipCounts.get(ip) || 0;
  if (ipCount >= PER_IP_MAX) {
    socket.destroy();
    console.warn(`[server] IP connection limit reached for ${ip}`);
    return;
  }

  // Global connection cap
  if (clients.size >= MAX_CONNECTIONS) {
    socket.destroy();
    console.warn('[server] Global connection limit reached');
    return;
  }

  if (shuttingDown) {
    socket.destroy();
    return;
  }

  wss.handleUpgrade(request, socket, head, (ws) => {
    wss.emit('connection', ws, request);
  });
});

// ---- WebSocket connection handling ----

wss.on('connection', (ws, request) => {
  const ip = (request.headers['x-real-ip'] || request.socket?.remoteAddress || 'unknown').toString();

  if (shuttingDown) {
    ws.close(1001, 'Server restarting');
    return;
  }

  ipCounts.set(ip, (ipCounts.get(ip) || 0) + 1);

  const meta = {
    player: null,
    v2Room: null,
    ip,
    tokenWindow: { tokens: BURST_LIMIT, resetAt: Date.now() + WINDOW_MS },
    lastChallengeAt: 0,
    alive: true,
    pingTimer: null,
  };
  clients.set(ws, meta);

  // Heartbeat
  const heartbeatTimer = setInterval(() => {
    if (meta.alive === false) {
      try { ws.terminate(); } catch { /* ignore */ }
      return;
    }
    meta.alive = false;
    ws.ping();
  }, HEARTBEAT_INTERVAL_MS);

  meta.pingTimer = heartbeatTimer;

  ws.on('pong', () => {
    meta.alive = true;
  });

  ws.on('message', (data, isBinary) => {
    // Only accept text messages
    if (isBinary) {
      ws.close(1003, 'Text messages only');
      return;
    }
    if (!checkRateLimit(meta)) {
      send(ws, { type: 'ERROR', message: 'Rate limit exceeded — slow down' });
      return;
    }

    let msg;
    try {
      msg = JSON.parse(data.toString());
    } catch {
      send(ws, { type: 'ERROR', message: 'Bad JSON' });
      return;
    }

    if (!validateMessage(msg)) {
      send(ws, { type: 'ERROR', message: 'Invalid message format' });
      return;
    }

    // ---- IDENTIFY_GUEST ----
    if (msg.type === 'IDENTIFY_GUEST') {
      // Version check
      if (msg.protocolVersion !== PROTOCOL_VERSION) {
        send(ws, {
          type: 'ERROR',
          message: `Protocol version mismatch. Please refresh the page. Expected version ${PROTOCOL_VERSION}.`,
        });
        return;
      }
      identifyGuest(ws);
      return;
    }

    // ---- V2 Identity required ----
    if (!requireV2Identity(ws)) return;
    const currentMeta = clients.get(ws);

    switch (msg.type) {
      case 'MATCH_REQUEST': {
        if (typeof msg.targetUserId !== 'string' || msg.targetUserId.length === 0 || msg.targetUserId.length > 200) {
          send(ws, { type: 'ERROR', message: 'Invalid targetUserId' });
          return;
        }
        const now = Date.now();
        if (now - currentMeta.lastChallengeAt < CHALLENGE_COOLDOWN_MS) {
          send(ws, { type: 'ERROR', message: 'Please wait before sending another challenge' });
          return;
        }
        currentMeta.lastChallengeAt = now;
        const result = matchLobby.request(currentMeta.player.id, msg.targetUserId);
        if (!result.ok) send(ws, { type: 'ERROR', message: result.error });
        break;
      }

      case 'MATCH_RESPONSE': {
        if (typeof msg.requestId !== 'string' || msg.requestId.length === 0 || msg.requestId.length > 200 || typeof msg.accept !== 'boolean') {
          send(ws, { type: 'ERROR', message: 'Invalid challenge response' });
          return;
        }
        const result = matchLobby.respond(currentMeta.player.id, msg.requestId, msg.accept);
        if (!result.ok) send(ws, { type: 'ERROR', message: result.error });
        break;
      }

      case 'MATCH_CANCEL': {
        if (typeof msg.requestId !== 'string' || msg.requestId.length === 0 || msg.requestId.length > 200) {
          send(ws, { type: 'ERROR', message: 'Invalid challenge request' });
          return;
        }
        const result = matchLobby.cancel(currentMeta.player.id, msg.requestId);
        if (!result.ok) send(ws, { type: 'ERROR', message: result.error });
        break;
      }

      case 'REMATCH_REQUEST': {
        const room = currentMeta.v2Room;
        if (!room) {
          send(ws, { type: 'ERROR', message: 'Not in a match' });
          return;
        }
        const requested = room.requestRematch(currentMeta.player.id);
        if (!requested.ok) {
          send(ws, { type: 'ERROR', message: requested.error });
          return;
        }

        if (requested.agreed) {
          const started = startV2Rematch(room);
          if (!started.ok) send(ws, { type: 'ERROR', message: started.error });
        } else {
          room.broadcast();
        }
        break;
      }

      case 'V2_MOVE': {
        const room = currentMeta.v2Room;
        if (!room) {
          send(ws, { type: 'ERROR', message: 'Not in a match' });
          return;
        }
        if (!Number.isInteger(msg.i) || !Number.isInteger(msg.j) || !Number.isInteger(msg.expectedRevision)) {
          send(ws, { type: 'ERROR', message: 'Invalid move payload' });
          return;
        }
        if (msg.i < 0 || msg.i >= 64 || msg.j < 0 || msg.j >= 64) {
          send(ws, { type: 'ERROR', message: 'Move index out of bounds' });
          return;
        }
        if (msg.expectedRevision < 0) {
          send(ws, { type: 'ERROR', message: 'Invalid revision' });
          return;
        }
        const res = room.tryMove(currentMeta.player.id, msg.i, msg.j, msg.expectedRevision);
        if (!res.ok) send(ws, { type: 'ERROR', message: res.error });
        break;
      }

      case 'V2_BET': {
        const room = currentMeta.v2Room;
        if (!room) {
          send(ws, { type: 'ERROR', message: 'Not in a match' });
          return;
        }
        if (!Number.isInteger(msg.expectedRevision) || !['check', 'call', 'raise', 'fold'].includes(msg.action)) {
          send(ws, { type: 'ERROR', message: 'Invalid bet payload' });
          return;
        }
        if (msg.expectedRevision < 0) {
          send(ws, { type: 'ERROR', message: 'Invalid revision' });
          return;
        }
        const res = room.tryBet(currentMeta.player.id, msg.action, msg.expectedRevision);
        if (!res.ok) send(ws, { type: 'ERROR', message: res.error });
        break;
      }

      case 'LEAVE_V2_MATCH': {
        leaveCurrentV2Match(ws);
        break;
      }

      default:
        send(ws, { type: 'ERROR', message: `Unknown message type: ${msg.type}` });
    }
  });

  ws.on('close', () => {
    clearInterval(heartbeatTimer);
    const currentMeta = clients.get(ws);
    if (currentMeta) {
      leaveCurrentV2Match(ws, 'Opponent disconnected');
      if (currentMeta.player) matchLobby.detach(ws, currentMeta.player.id);
      ipCounts.set(currentMeta.ip, Math.max(0, (ipCounts.get(currentMeta.ip) || 1) - 1));
      if (ipCounts.get(currentMeta.ip) === 0) ipCounts.delete(currentMeta.ip);
      clients.delete(ws);
    }
  });

  ws.on('error', () => {
    // handled in close
  });
});

httpServer.listen(PORT, () => {
  console.log(`[server] PanicRadar BlockCoined V2 PvP server listening on port ${PORT}`);
  console.log(`[server] Mode: ${process.env.NODE_ENV || 'development'}`);
  console.log(`[server] Allowed origins: ${ALLOWED_ORIGINS.length ? ALLOWED_ORIGINS.join(', ') : '(fail-closed)'}`);
  console.log(`[server] Demo credits reset on restart. Guest identities are temporary.`);
});
