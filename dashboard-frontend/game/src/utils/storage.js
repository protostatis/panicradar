/**
 * storage.js — client-side persistence for PvP guest session data.
 *
 * Stores the opaque session token (issued by the game server) in localStorage
 * so that page reloads / tab closures restore the same guest identity and
 * credit balance (within the server's lifetime).
 *
 * The server never trusts client-stored balances — only the session token is
 * meaningful.  The userId and name are cached alongside for immediate UI use
 * without waiting for a round-trip.
 */

const STORAGE_KEY = 'bc2_pvp_session';

/**
 * @typedef {{ sessionToken: string, userId: string, name: string }} PvpSession
 */

/** Read the persisted PvP session, or null if absent / corrupt. */
export function loadSession() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (
      typeof parsed.sessionToken === 'string' &&
      parsed.sessionToken.length > 0 &&
      typeof parsed.userId === 'string' &&
      typeof parsed.name === 'string'
    ) {
      return parsed;
    }
  } catch {
    // Corrupt or unavailable — treat as no session
  }
  return null;
}

/** Persist the PvP session (token + identity) to localStorage.
 *  Validates that all required fields are non-empty strings before writing.
 *  Returns true if the session was persisted, false otherwise. */
export function saveSession(session) {
  if (
    !session ||
    typeof session.sessionToken !== 'string' ||
    session.sessionToken.length === 0 ||
    typeof session.userId !== 'string' ||
    session.userId.length === 0 ||
    typeof session.name !== 'string' ||
    session.name.length === 0
  ) {
    return false;
  }
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      sessionToken: session.sessionToken,
      userId: session.userId,
      name: session.name,
    }));
    return true;
  } catch {
    return false;
  }
}

/** Remove the persisted session (explicit "new identity" action). */
export function clearSession() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
