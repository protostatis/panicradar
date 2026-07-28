/**
 * SessionStore.test.js — unit tests for opaque session token store.
 *
 * Run:  node --test server/SessionStore.test.js
 */

import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { SessionStore } from './SessionStore.js';

/* ------------------------------------------------------------------ */
/*  Token format                                                       */
/* ------------------------------------------------------------------ */

const TOKEN_REGEX = /^[A-Za-z0-9\-_]{43}$/; // 32 bytes → 43 base64url chars (no padding)

function decodeBase64url(s) {
  return Buffer.from(s, 'base64url');
}

describe('session token format', () => {
  test('generated tokens are 43-character base64url strings', () => {
    const store = new SessionStore();
    for (let i = 0; i < 20; i++) {
      const { token } = store.getOrCreate();
      assert.match(token, TOKEN_REGEX, `token ${token} should match base64url pattern`);
    }
  });

  test('generated tokens decode to exactly 32 bytes', () => {
    const store = new SessionStore();
    for (let i = 0; i < 20; i++) {
      const { token } = store.getOrCreate();
      const decoded = decodeBase64url(token);
      assert.equal(decoded.length, 32, `token ${token} should decode to 32 bytes, got ${decoded.length}`);
    }
  });

  test('successive tokens are unique', () => {
    const store = new SessionStore();
    const tokens = new Set();
    for (let i = 0; i < 100; i++) {
      const { token } = store.getOrCreate();
      tokens.add(token);
    }
    assert.equal(tokens.size, 100);
  });
});

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

let counter = 0;
function createPlayer() {
  counter++;
  return { id: `test_user_${counter}`, name: `TestPlayer${counter}` };
}

function freshStore(maxSessions = 100) {
  counter = 0;
  return new SessionStore({ createPlayer, maxSessions });
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('SessionStore.getOrCreate', () => {
  test('creates a new session when no token is given', () => {
    const store = freshStore();
    const s1 = store.getOrCreate();

    assert.ok(s1.token, 'should generate a token');
    assert.equal(typeof s1.token, 'string');
    assert.ok(s1.token.length > 0);
    assert.equal(s1.userId, 'test_user_1');
    assert.equal(s1.name, 'TestPlayer1');
    assert.equal(store.size, 1);
  });

  test('returns the same session for a known token', () => {
    const store = freshStore();
    const s1 = store.getOrCreate();

    const s2 = store.getOrCreate(s1.token);
    assert.equal(s2.token, s1.token, 'token should match');
    assert.equal(s2.userId, s1.userId, 'userId should match');
    assert.equal(s2.name, s1.name, 'name should match');
    assert.equal(store.size, 1, 'should not create a new entry');
  });

  test('creates a fresh session for an unknown token', () => {
    const store = freshStore();
    const s1 = store.getOrCreate();
    const s2 = store.getOrCreate('nonexistent-token');

    assert.notEqual(s2.userId, s1.userId, 'should be different user');
    assert.notEqual(s2.name, s1.name, 'should be different name');
    assert.equal(store.size, 2);
  });

  test('handles empty string token as unknown', () => {
    const store = freshStore();
    const s1 = store.getOrCreate('');

    const s2 = store.getOrCreate('');
    assert.notEqual(s2.token, s1.token, 'empty string should create fresh each time');
    assert.equal(store.size, 2);
  });

  test('multiple getOrCreate calls without token create unique entries', () => {
    const store = freshStore();
    const s1 = store.getOrCreate();
    const s2 = store.getOrCreate();
    const s3 = store.getOrCreate();

    assert.equal(store.size, 3);
    assert.notEqual(s1.userId, s2.userId);
    assert.notEqual(s2.userId, s3.userId);
  });
});

/* ------------------------------------------------------------------ */
/*  Eviction                                                           */
/* ------------------------------------------------------------------ */

describe('SessionStore eviction', () => {
  test('evicts oldest session when at capacity', () => {
    const store = freshStore(3); // max 3 sessions

    const s1 = store.getOrCreate();
    const s2 = store.getOrCreate();
    const s3 = store.getOrCreate();
    assert.equal(store.size, 3);

    // Fourth creation should evict s1
    const s4 = store.getOrCreate();
    assert.equal(store.size, 3);
    assert.equal(store.has(s1.token), false, 'oldest should be evicted');
    assert.equal(store.has(s2.token), true);
    assert.equal(store.has(s3.token), true);
    assert.equal(store.has(s4.token), true);
  });

  test('evicted token is no longer restorable', () => {
    const store = freshStore(2);

    const s1 = store.getOrCreate();
    const s2 = store.getOrCreate();
    store.getOrCreate(); // evicts s1

    const restored = store.getOrCreate(s1.token);
    assert.notEqual(restored.userId, s1.userId, 'evicted token should not restore old identity');
    assert.equal(store.size, 2);
  });
});

/* ------------------------------------------------------------------ */
/*  Identity restoration (same token → same identity)                  */
/* ------------------------------------------------------------------ */

describe('SessionStore identity restoration', () => {
  test('same token always returns same userId regardless of order', () => {
    const store = freshStore();
    const s1 = store.getOrCreate();

    // Interleave other sessions
    store.getOrCreate();
    store.getOrCreate();

    const restored = store.getOrCreate(s1.token);
    assert.equal(restored.userId, s1.userId);
    assert.equal(restored.name, s1.name);
  });

  test('survives until eviction threshold', () => {
    const store = freshStore(5);
    const ids = new Set();

    // Fill 3 sessions
    for (let i = 0; i < 3; i++) {
      const s = store.getOrCreate();
      ids.add(s.userId);
    }

    // Restore each one
    for (const id of ids) {
      // Find the token by scanning — in practice the client sends the token
      let found = false;
      for (const [token, entry] of store._sessions) {
        if (entry.userId === id) {
          const restored = store.getOrCreate(token);
          assert.equal(restored.userId, id);
          found = true;
          break;
        }
      }
      assert.ok(found, `user ${id} should be restorable`);
    }
  });
});
