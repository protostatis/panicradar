/**
 * SessionStore.js — opaque bearer-token session store for PvP guest identity
 * persistence.
 *
 * Tokens are 32-byte base64url (256-bit). Stored in client localStorage and
 * sent with IDENTIFY_GUEST on reconnect to restore the same guest identity.
 * Bounded to MAX_SESSIONS — evicts oldest entries when full.
 *
 * In-memory only (Phase 1). All sessions are lost on server restart.
 */

import { randomBytes } from 'crypto';

const SESSION_TOKEN_BYTES = 32;

function generateSessionToken() {
  return randomBytes(SESSION_TOKEN_BYTES).toString('base64url');
}

export class SessionStore {
  /**
   * @param {object} [opts]
   * @param {number} [opts.maxSessions=10000]
   * @param {() => { id: string, name: string }} [opts.createPlayer]
   */
  constructor(opts = {}) {
    this._maxSessions = opts.maxSessions || 10_000;
    this._createPlayer = opts.createPlayer || (() => ({
      id: `guest_${randomBytes(12).toString('base64url')}`,
      name: `Player_${randomBytes(4).toString('hex')}`,
    }));
    /** @type {Map<string, { userId: string, name: string }>} */
    this._sessions = new Map();
  }

  /** Current number of stored sessions. */
  get size() {
    return this._sessions.size;
  }

  /** Look up an existing session or create a new one.
   *  Returns { token: string, userId: string, name: string }. */
  getOrCreate(sessionToken) {
    if (sessionToken && this._sessions.has(sessionToken)) {
      return this._sessions.get(sessionToken);
    }

    if (this._sessions.size >= this._maxSessions) {
      // Evict the oldest session (Map insertion order = oldest first)
      const oldest = this._sessions.keys().next().value;
      if (oldest) this._sessions.delete(oldest);
    }

    const token = generateSessionToken();
    const player = this._createPlayer();
    const entry = { token, userId: player.id, name: player.name };
    this._sessions.set(token, entry);
    return entry;
  }

  /** Check whether a token exists (for testing). */
  has(token) {
    return this._sessions.has(token);
  }
}

export default SessionStore;
