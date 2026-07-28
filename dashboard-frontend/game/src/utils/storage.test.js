/**
 * storage.test.js — unit tests for PvP guest session persistence.
 *
 * Runs under vitest's node environment; localStorage is mocked via
 * globalThis stubs since jsdom is not a project dependency.
 */
import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { loadSession, saveSession, clearSession } from './storage';

/** Minimal in-memory localStorage replacement. */
function createMockStorage() {
  const store = {};
  return {
    getItem(key) { return store[key] ?? null; },
    setItem(key, value) { store[key] = String(value); },
    removeItem(key) { delete store[key]; },
    clear() { Object.keys(store).forEach((k) => delete store[k]); },
    get length() { return Object.keys(store).length; },
    key(i) { return Object.keys(store)[i] ?? null; },
  };
}

let mockStorage;

beforeEach(() => {
  mockStorage = createMockStorage();
  globalThis.localStorage = mockStorage;
});

afterEach(() => {
  delete globalThis.localStorage;
});

/* ------------------------------------------------------------------ */
/*  Round-trip tests                                                   */
/* ------------------------------------------------------------------ */

describe('saveSession / loadSession', () => {
  it('persists a valid session and reads it back', () => {
    const session = { sessionToken: 'abc123', userId: 'guest_xyz', name: 'Amber Badger' };
    saveSession(session);
    expect(loadSession()).toEqual(session);
  });

  it('overwrites an existing session on subsequent save', () => {
    const first = { sessionToken: 'tok1', userId: 'uid1', name: 'First' };
    const second = { sessionToken: 'tok2', userId: 'uid2', name: 'Second' };
    saveSession(first);
    saveSession(second);
    expect(loadSession()).toEqual(second);
  });

  it('returns null when no session has been saved', () => {
    expect(loadSession()).toBeNull();
  });

  it('handles special characters in name', () => {
    const session = { sessionToken: 'tok', userId: 'uid', name: "Cöbra O'Malley—Viper" };
    saveSession(session);
    expect(loadSession()).toEqual(session);
  });

  it('returns true on successful save', () => {
    const result = saveSession({ sessionToken: 'tok', userId: 'uid', name: 'Name' });
    expect(result).toBe(true);
  });
});

/* ------------------------------------------------------------------ */
/*  saveSession validation                                             */
/* ------------------------------------------------------------------ */

describe('saveSession validation', () => {
  it('rejects null', () => {
    expect(saveSession(null)).toBe(false);
    expect(loadSession()).toBeNull();
  });

  it('rejects undefined', () => {
    expect(saveSession(undefined)).toBe(false);
    expect(loadSession()).toBeNull();
  });

  it('rejects empty sessionToken', () => {
    expect(saveSession({ sessionToken: '', userId: 'uid', name: 'Name' })).toBe(false);
    expect(loadSession()).toBeNull();
  });

  it('rejects non-string sessionToken', () => {
    expect(saveSession({ sessionToken: 123, userId: 'uid', name: 'Name' })).toBe(false);
    expect(loadSession()).toBeNull();
  });

  it('rejects missing userId', () => {
    expect(saveSession({ sessionToken: 'tok', name: 'Name' })).toBe(false);
  });

  it('rejects empty userId', () => {
    expect(saveSession({ sessionToken: 'tok', userId: '', name: 'Name' })).toBe(false);
  });

  it('rejects missing name', () => {
    expect(saveSession({ sessionToken: 'tok', userId: 'uid' })).toBe(false);
  });

  it('rejects empty name', () => {
    expect(saveSession({ sessionToken: 'tok', userId: 'uid', name: '' })).toBe(false);
  });

  it('rejects extra unknown properties but valid fields still saves', () => {
    const result = saveSession({ sessionToken: 'tok', userId: 'uid', name: 'Name', extra: 'ignored' });
    expect(result).toBe(true);
    const loaded = loadSession();
    expect(loaded.sessionToken).toBe('tok');
    expect(loaded.extra).toBeUndefined();
  });
});

/* ------------------------------------------------------------------ */
/*  Corruption / edge cases                                            */
/* ------------------------------------------------------------------ */

describe('loadSession — corruption resilience', () => {
  it('returns null for missing key', () => {
    expect(loadSession()).toBeNull();
  });

  it('returns null for malformed JSON', () => {
    mockStorage.setItem('bc2_pvp_session', '{bad json');
    expect(loadSession()).toBeNull();
  });

  it('returns null for non-object JSON', () => {
    mockStorage.setItem('bc2_pvp_session', '"just a string"');
    expect(loadSession()).toBeNull();
  });

  it('returns null for empty object', () => {
    mockStorage.setItem('bc2_pvp_session', '{}');
    expect(loadSession()).toBeNull();
  });

  it('returns null when sessionToken is missing', () => {
    mockStorage.setItem('bc2_pvp_session', JSON.stringify({ userId: 'uid', name: 'Name' }));
    expect(loadSession()).toBeNull();
  });

  it('returns null when sessionToken is empty string', () => {
    mockStorage.setItem('bc2_pvp_session', JSON.stringify({ sessionToken: '', userId: 'uid', name: 'Name' }));
    expect(loadSession()).toBeNull();
  });

  it('returns null when userId is missing', () => {
    mockStorage.setItem('bc2_pvp_session', JSON.stringify({ sessionToken: 'tok', name: 'Name' }));
    expect(loadSession()).toBeNull();
  });

  it('returns null when name is missing', () => {
    mockStorage.setItem('bc2_pvp_session', JSON.stringify({ sessionToken: 'tok', userId: 'uid' }));
    expect(loadSession()).toBeNull();
  });

  it('returns null when name is not a string', () => {
    mockStorage.setItem('bc2_pvp_session', JSON.stringify({ sessionToken: 'tok', userId: 'uid', name: 42 }));
    expect(loadSession()).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/*  clearSession                                                       */
/* ------------------------------------------------------------------ */

describe('clearSession', () => {
  it('removes the stored session', () => {
    saveSession({ sessionToken: 'tok', userId: 'uid', name: 'Name' });
    clearSession();
    expect(loadSession()).toBeNull();
  });

  it('is a no-op when no session is stored', () => {
    clearSession();
    expect(loadSession()).toBeNull();
  });
});

/* ------------------------------------------------------------------ */
/*  localStorage unavailable                                           */
/* ------------------------------------------------------------------ */

describe('when localStorage is unavailable', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'localStorage', {
      get() { throw new Error('localStorage denied'); },
      configurable: true,
    });
  });

  it('saveSession does not throw', () => {
    expect(() => saveSession({ sessionToken: 't', userId: 'u', name: 'n' })).not.toThrow();
  });

  it('loadSession returns null without throwing', () => {
    expect(loadSession()).toBeNull();
  });

  it('clearSession does not throw', () => {
    expect(() => clearSession()).not.toThrow();
  });
});
