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

// ---- AudioContext — eager creation (no gesture needed) ----

if (typeof window !== 'undefined') {
  const Ctor = window.AudioContext || window.webkitAudioContext;
  if (Ctor) {
    ctx = new Ctor();
  }
}

// ---- Unlock on first gesture ----

async function preload() {
  if (loadPromise) return loadPromise;
  if (!ctx || buffer) return;
  loadPromise = (async () => {
    try {
      const resp = await fetch(chaching);
      if (!resp.ok) throw new Error(`Audio fetch failed: ${resp.status}`);
      const raw = await resp.arrayBuffer();
      buffer = await ctx.decodeAudioData(raw);
    } catch {
      loadPromise = null; // allow retry on next playScoreSound call
    }
  })();
  await loadPromise;
}

function onFirstGesture() {
  if (ctx && ctx.state === 'suspended') {
    ctx.resume().catch(() => {});
  }
  preload();
}

if (typeof document !== 'undefined' && ctx) {
  const handler = () => {
    onFirstGesture();
    document.removeEventListener('pointerdown', handler, true);
    document.removeEventListener('keydown', handler, true);
  };
  document.addEventListener('pointerdown', handler, true);
  document.addEventListener('keydown', handler, true);
}

// ---- Play helpers ----

/** Internal: play from the decoded buffer. */
function playBuffer() {
  if (!ctx || !buffer) return;
  // If context is suspended (e.g. Safari tab switch), try to resume.
  if (ctx.state === 'suspended') {
    ctx.resume().catch(() => {});
  }
  if (ctx.state === 'closed') return;
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
 * AudioContext must be unlocked by a user gesture before audio plays.
 * Once unlocked and the MP3 is decoded, this works from any calling context
 * (WebSocket onmessage, timers, etc.). If the buffer is still loading the
 * call is silently skipped — the next play will succeed.
 */
export function playScoreSound() {
  if (!enabled || !ctx) return;
  if (!buffer) {
    preload(); // background load for next time
    return;
  }
  playBuffer();
}
