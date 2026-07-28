/**
 * v2PvpTransport.js — V2 WebSocket transport for lobby-matched PvP games.
 *
 * Guest-only adaptation for PanicRadar:
 *  - Derives ws/wss from location.host with exact /game/ws.
 *  - Permits VITE_PVP_URL override only for local development.
 *  - Versioned protocol handshake (protocolVersion 1 in IDENTIFY_GUEST).
 *  - Session token in localStorage persists guest identity across page loads.
 *  - Bounded reconnect/backoff for lobby disconnections only.
 *  - No Google auth import, config, module, or CSP references.
 */
import { loadSession, saveSession } from '../utils/storage';

const PROTOCOL_VERSION = 1;

function devOverrideUrl() {
  if (import.meta.env.VITE_PVP_URL) return import.meta.env.VITE_PVP_URL;
  return null;
}

function buildWsUrl() {
  const override = devOverrideUrl();
  if (override) return override;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/game/ws`;
}

export class V2PvpTransport {
  constructor() {
    this.ws = null;
    this.listeners = new Set();
    this.lastSnapshot = null;
    this.lastLobbySnapshot = null;
    this.identity = null;
    this._requestId = 0;
    this.expectedRevision = -1;
    this._connectPromise = null;
    this._intentionalClose = false;
    this._connectedOnce = false;
    this._inMatch = false;
    this._reconnectAttempts = 0;
    this._reconnectTimer = null;
  }

  _nextRequestId() {
    return ++this._requestId;
  }

  onMessage(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  _emit(msg) {
    for (const fn of this.listeners) fn(msg);
  }

  /** Connect as a server-issued guest identity. */
  connect() {
    if (this.ws?.readyState === WebSocket.OPEN && this.identity) {
      return Promise.resolve(this.identity);
    }
    if (this._connectPromise) return this._connectPromise;

    this._intentionalClose = false;
    return this._open(false);
  }

  _open(isReconnect) {
    const connection = new Promise((resolve, reject) => {
      const ws = new WebSocket(buildWsUrl());
      this.ws = ws;
      let settled = false;
      let handshakeTimer = null;

      // Read persisted session token for identity restoration.
      const persistedSession = loadSession();
      const sessionToken = persistedSession?.sessionToken;

      const resolveConnection = (identity) => {
        if (settled) return;
        settled = true;
        clearTimeout(handshakeTimer);
        resolve(identity);
      };

      const rejectConnection = (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(handshakeTimer);
        reject(error);
      };

      handshakeTimer = setTimeout(() => {
        rejectConnection(new Error('Lobby handshake timed out'));
        try { ws.close(1000, 'Handshake timeout'); } catch { /* ignore */ }
      }, 10_000);

      ws.onopen = () => {
        const handshake = { type: 'IDENTIFY_GUEST', protocolVersion: PROTOCOL_VERSION };
        if (sessionToken) handshake.sessionToken = sessionToken;
        this._send(handshake);
      };

      ws.onmessage = (ev) => {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }

        if (msg.type === 'IDENTITY_OK') {
          this.identity = msg.self;
          this._connectedOnce = true;
          this._reconnectAttempts = 0;
          resolveConnection(msg.self);
          // Persist the session token + identity so reloads restore them.
          // saveSession validates all fields internally before writing.
          saveSession({
            sessionToken: msg.sessionToken,
            userId: msg.self?.userId,
            name: msg.self?.name,
          });
        }
        if (msg.type === 'LOBBY_SNAPSHOT') this.lastLobbySnapshot = msg;
        if (msg.type === 'V2_SNAPSHOT') {
          this.lastSnapshot = msg;
          this.expectedRevision = msg.revision;
          if (msg.lifecycle === 'active') this._inMatch = true;
        }
        if (msg.type === 'MATCH_STARTED' || msg.type === 'REMATCH_STARTED') {
          this._inMatch = true;
          if (msg.type === 'REMATCH_STARTED') {
            // New room has its own revision sequence; reset stale state.
            this.lastSnapshot = null;
            this.expectedRevision = -1;
          }
        }
        if (msg.type === 'MATCH_ENDED') {
          this._inMatch = false;
          this.lastSnapshot = null;
          this.expectedRevision = -1;
        }
        if (msg.type === 'ERROR' && !this.identity) {
          rejectConnection(new Error(msg.message || 'Server error'));
          ws.close(1002, 'Handshake rejected');
        }

        this._emit(msg);
        if (msg.type === 'IDENTITY_OK' && isReconnect) {
          this._emit({ type: 'SYSTEM', text: 'Reconnected to the match lobby' });
        }
      };

      ws.onerror = () => {
        rejectConnection(new Error('Connection error'));
      };

      ws.onclose = (ev) => {
        if (this.ws !== ws) return;
        this.ws = null;
        rejectConnection(new Error(ev.reason || 'Disconnected'));

        if (this._intentionalClose) return;

        const reason = ev.reason || 'Disconnected';
        const wasInMatch = this._inMatch;
        this.identity = null;
        this.lastLobbySnapshot = null;
        this.expectedRevision = -1;
        this._inMatch = false;

        if (wasInMatch) {
          this.lastSnapshot = null;
          this._emit({ type: 'MATCH_ENDED', message: 'Connection lost — the match was forfeited' });
        }
        this._emit({ type: 'SYSTEM', text: reason });
        if (this._connectedOnce) this._scheduleReconnect();
      };
    });

    this._connectPromise = connection;
    return connection.finally(() => {
      if (this._connectPromise === connection) this._connectPromise = null;
    });
  }

  _scheduleReconnect() {
    if (this._intentionalClose || this._reconnectTimer) return;
    if (this._reconnectAttempts >= 5) {
      this._emit({ type: 'ERROR', message: 'Unable to reconnect. Return to the menu and try again.' });
      return;
    }

    const delayMs = Math.min(500 * (2 ** this._reconnectAttempts), 8_000);
    this._reconnectAttempts++;
    this._emit({ type: 'SYSTEM', text: `Reconnecting in ${Math.ceil(delayMs / 1000)}s…` });
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      if (!this._intentionalClose) this._open(true).catch(() => {});
    }, delayMs);
  }

  _send(obj) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  requestMatch(targetUserId) {
    this._send({ type: 'MATCH_REQUEST', targetUserId });
  }

  respondToMatch(requestId, accept) {
    this._send({ type: 'MATCH_RESPONSE', requestId, accept });
  }

  cancelMatch(requestId) {
    this._send({ type: 'MATCH_CANCEL', requestId });
  }

  requestRematch() {
    this._send({ type: 'REMATCH_REQUEST' });
  }

  move(i, j) {
    this._send({
      type: 'V2_MOVE',
      i,
      j,
      expectedRevision: this.expectedRevision,
      requestId: this._nextRequestId(),
    });
  }

  bet(action) {
    this._send({
      type: 'V2_BET',
      action,
      expectedRevision: this.expectedRevision,
      requestId: this._nextRequestId(),
    });
  }

  leaveMatch() {
    this._send({ type: 'LEAVE_V2_MATCH' });
  }

  close() {
    this._intentionalClose = true;
    clearTimeout(this._reconnectTimer);
    this._reconnectTimer = null;
    const ws = this.ws;
    this.ws = null;
    this.identity = null;
    this.lastLobbySnapshot = null;
    this.lastSnapshot = null;
    this.expectedRevision = -1;
    this._inMatch = false;
    if (ws) ws.close();
  }
}
