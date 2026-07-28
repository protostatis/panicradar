/**
 * Sound effects. Uses Web Audio API for reliable playback outside user
 * gesture contexts (e.g. WebSocket callbacks in PvP).
 *
 * An AudioContext is created eagerly on module load. A global first-gesture
 * listener (pointerdown / keydown) resumes the context and kicks off MP3
 * preloading. After that, source.start() works from any calling context
 * (WebSocket onmessage, timers, etc.). A new BufferSource is created per
 * play so overlapping scores don't cut each other off.
 */
import chaching from '../sound/Cha-ching-sound.mp3';

let enabled = true;

/** @type {AudioContext|null} */
let ctx = null;

/** @type {AudioBuffer|null} */
let buffer = null;

/** @type {Promise<void>|null} */
let loadPromise = null;

/** Queue of plays that arrived before the buffer finished loading. */
let pendingPlays = 0;

/** @type {(()=>void)|null} */
let removeListener = null;

// ---- AudioContext — eager creation (no gesture needed) ----

if (typeof window !== 'undefined') {
  const Ctor = window.AudioContext || window.webkitAudioContext;
  if (Ctor) {
    ctx = new Ctor();
  }
}

// ---- Unlock on first gesture ----

function ensureRunning() {
  if (!ctx) return;
  if (ctx.state === 'suspended') {
    ctx.resume().catch(() => {});
  }
  // Safari may enter 'interrupted' after a tab switch; re-create if so.
  if (ctx.state === 'closed') {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (Ctor) {
      ctx = new Ctor();
      // Start preload again for the new context.
      loadPromise = null;
      buffer = null;
      preload();
    }
  }
}

async function preload() {
  if (loadPromise) return loadPromise;
  if (!ctx || buffer) return Promise.resolve();
  loadPromise = (async () => {
    try {
      const resp = await fetch(chaching);
      if (!resp.ok) throw new Error(`Audio fetch failed: ${resp.status}`);
      const raw = await resp.arrayBuffer();
      buffer = await ctx.decodeAudioData(raw);
      // Flush any plays that were queued while the buffer was loading.
      // For each, create and schedule a source node with the freshly
      // decoded buffer.
      if (buffer && pendingPlays > 0) {
        for (let i = 0; i < pendingPlays; i++) {
          playBuffer();
        }
        pendingPlays = 0;
      }
    } catch {
      loadPromise = null; // allow retry on next playScoreSound call
    }
  })();
  return loadPromise;
}

function onFirstGesture() {
  if (removeListener) {
    removeListener();
    removeListener = null;
  }
  ensureRunning();
  // Start preloading the MP3 now — the first score may arrive before the
  // buffer is decoded, but subsequent ones will play instantly.
  preload();
}

if (typeof document !== 'undefined' && ctx) {
  const down = () => { onFirstGesture(); };
  const key = () => { onFirstGesture(); };
  document.addEventListener('pointerdown', down, true);
  document.addEventListener('keydown', key, true);
  removeListener = () => {
    document.removeEventListener('pointerdown', down, true);
    document.removeEventListener('keydown', key, true);
  };
}

// ---- Play helpers ----

/** Internal: play from the decoded buffer (must be non-null). */
function playBuffer() {
  if (!ctx || !buffer) return;
  try {
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    const gain = ctx.createGain();
    gain.gain.value = 0.6;
    src.connect(gain);
    gain.connect(ctx.destination);
    src.start(0);
  } catch {
    /* audio not available — ignore */
  }
}

// ---- Public API ----

export function setSoundEnabled(on) {
  enabled = !!on;
}

export function isSoundEnabled() {
  return enabled;
}

/**
 * Play the score "cha-ching". Safe to call repeatedly; ignores failures.
 *
 * The AudioContext must be unlocked by a user gesture before audio plays.
 * Once unlocked and the MP3 buffer is loaded, this works from any calling
 * context (WebSocket onmessage, timers, etc.).
 */
export function playScoreSound() {
  if (!enabled || !ctx) return;

  if (!buffer) {
    // Buffer not yet loaded — queue this play and kick off loading if not
    // already in-flight.  The queue is flushed when decoding completes.
    pendingPlays++;
    preload();
    return;
  }

  playBuffer();
}
