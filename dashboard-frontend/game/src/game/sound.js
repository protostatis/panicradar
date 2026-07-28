/**
 * Sound effects. Uses Web Audio API for reliable playback outside user
 * gesture contexts (e.g. WebSocket callbacks in PvP). The AudioContext is
 * created on first import and unlocked on the first user interaction via a
 * global pointer-down listener — after that, source.start() works from any
 * calling context. A new BufferSource is created per play so overlapping
 * scores don't cut each other off.
 */
import chaching from '../sound/Cha-ching-sound.mp3';

let enabled = true;

/** @type {AudioContext|null} */
let ctx = null;

/** @type {AudioBuffer|null} */
let buffer = null;

let unlockPending = true;

function getContext() {
  if (!ctx && typeof window !== 'undefined') {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    ctx = new Ctor();
  }
  return ctx;
}

/** Unlock the AudioContext on first user gesture. */
function unlock() {
  if (!unlockPending) return;
  unlockPending = false;
  if (ctx && ctx.state === 'suspended') {
    ctx.resume().catch(() => {});
  }
}

// Register global unlock — pointerdown fires before click and covers touch/pen.
if (typeof document !== 'undefined') {
  const handler = () => { unlock(); document.removeEventListener('pointerdown', handler, true); };
  document.addEventListener('pointerdown', handler, true);
}

async function loadBuffer() {
  if (buffer) return;
  const c = getContext();
  if (!c) return;
  try {
    const resp = await fetch(chaching);
    const raw = await resp.arrayBuffer();
    buffer = await c.decodeAudioData(raw);
  } catch {
    /* can't decode — sound stays silent */
  }
}

export function setSoundEnabled(on) {
  enabled = !!on;
}

export function isSoundEnabled() {
  return enabled;
}

/**
 * Play the score "cha-ching". Safe to call repeatedly; ignores failures.
 *
 * First call triggers buffer loading (the promise is cached). Once the
 * AudioContext is unlocked via user gesture, all subsequent plays work
 * even from non-gesture contexts (WebSocket onmessage, timers, etc.).
 */
export function playScoreSound() {
  if (!enabled) return;

  const c = getContext();
  if (!c) return;

  if (!buffer) {
    // Kick off background load; sound for this call is best-effort.
    loadBuffer();
    // Fallback: try the old HTMLAudioElement approach for the first play.
    try {
      const a = new Audio(chaching);
      a.volume = 0.6;
      const p = a.play();
      if (p && typeof p.catch === 'function') p.catch(() => {});
    } catch {
      /* ignore */
    }
    return;
  }

  try {
    const src = c.createBufferSource();
    src.buffer = buffer;
    const gain = c.createGain();
    gain.gain.value = 0.6;
    src.connect(gain);
    gain.connect(c.destination);
    src.start(0);
  } catch {
    /* audio not available — ignore */
  }
}
