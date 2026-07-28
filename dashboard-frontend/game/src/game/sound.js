/**
 * Sound effects. Uses Web Audio so server-driven PvP score events can play
 * after the browser's audio context has been unlocked by a user gesture.
 *
 * Mobile WebKit is stricter than desktop browsers: create/resume the context
 * from touchend, click, or keydown, and synchronously start a silent source.
 * Keep retrying on later gestures until the context is actually running.
 */
import chaching from '../sound/Cha-ching-sound.mp3';

const UNLOCK_EVENTS = ['touchend', 'click', 'keydown'];

let enabled = true;
/** @type {AudioContext|null} */
let ctx = null;
/** @type {AudioBuffer|null} */
let buffer = null;
/** @type {Promise<void>|null} */
let loadPromise = null;
let contextGeneration = 0;
let listenersArmed = false;
let pendingPlay = false;
/** @type {AudioContext|null} */
let silentStartedFor = null;

function audioContextConstructor() {
  if (typeof window === 'undefined') return null;
  return window.AudioContext || window.webkitAudioContext || null;
}

function onContextStateChange(context) {
  if (context !== ctx) return;
  if (context.state === 'running') {
    disarmUnlockListeners();
    preload(context);
  } else {
    armUnlockListeners();
  }
}

function ensureContext() {
  if (ctx && ctx.state !== 'closed') return ctx;

  const Ctor = audioContextConstructor();
  if (!Ctor) return null;

  try {
    ctx = new Ctor();
  } catch {
    ctx = null;
    return null;
  }

  contextGeneration += 1;
  buffer = null;
  loadPromise = null;
  silentStartedFor = null;

  const context = ctx;
  if (typeof context.addEventListener === 'function') {
    context.addEventListener('statechange', () => onContextStateChange(context));
  } else {
    context.onstatechange = () => onContextStateChange(context);
  }
  return context;
}

function startSilentUnlock(context) {
  if (silentStartedFor === context) return;
  try {
    const source = context.createBufferSource();
    source.buffer = context.createBuffer(1, 1, 22_050);
    source.connect(context.destination);
    source.onended = () => {
      try { source.disconnect(); } catch { /* ignore */ }
    };
    source.start(0);
    silentStartedFor = context;
  } catch {
    // A later supported gesture can retry resume even if this source fails.
  }
}

function completeUnlock(context) {
  if (context !== ctx) return;
  if (context.state !== 'running') {
    armUnlockListeners();
    return;
  }
  disarmUnlockListeners();
  preload(context);
}

function attemptUnlock() {
  const context = ensureContext();
  if (!context) return;

  let resumePromise = null;
  if (context.state !== 'running') {
    try {
      resumePromise = context.resume();
    } catch {
      armUnlockListeners();
    }
  }

  // Do not await resume: source.start() must remain in the trusted gesture
  // call stack for iOS Safari.
  startSilentUnlock(context);

  if (context.state === 'running') completeUnlock(context);
  if (resumePromise && typeof resumePromise.then === 'function') {
    resumePromise
      .then(() => completeUnlock(context))
      .catch(() => armUnlockListeners());
  }
}

function armUnlockListeners() {
  if (listenersArmed || typeof document === 'undefined') return;
  for (const eventName of UNLOCK_EVENTS) {
    document.addEventListener(eventName, attemptUnlock, true);
  }
  listenersArmed = true;
}

function disarmUnlockListeners() {
  if (!listenersArmed || typeof document === 'undefined') return;
  for (const eventName of UNLOCK_EVENTS) {
    document.removeEventListener(eventName, attemptUnlock, true);
  }
  listenersArmed = false;
}

async function preload(context) {
  if (context !== ctx || context.state !== 'running' || buffer) return;
  if (loadPromise) return loadPromise;

  const generation = contextGeneration;
  const pending = (async () => {
    try {
      const response = await fetch(chaching);
      if (!response.ok) throw new Error(`Audio fetch failed: ${response.status}`);
      const raw = await response.arrayBuffer();
      const decoded = await context.decodeAudioData(raw);
      if (context !== ctx || generation !== contextGeneration) return;

      buffer = decoded;
      if (pendingPlay && enabled) {
        pendingPlay = false;
        playBuffer(context, decoded);
      }
    } catch {
      if (context === ctx && generation === contextGeneration) {
        pendingPlay = false;
      }
    }
  })();

  loadPromise = pending;
  try {
    await pending;
  } finally {
    if (context === ctx && generation === contextGeneration && loadPromise === pending) {
      loadPromise = null;
    }
  }
}

function playBuffer(context, audioBuffer) {
  if (!enabled || context !== ctx || context.state !== 'running') {
    armUnlockListeners();
    return;
  }

  try {
    const source = context.createBufferSource();
    const gain = context.createGain();
    source.buffer = audioBuffer;
    gain.gain.value = 0.6;
    source.connect(gain);
    gain.connect(context.destination);
    source.onended = () => {
      try { source.disconnect(); } catch { /* ignore */ }
      try { gain.disconnect(); } catch { /* ignore */ }
    };
    source.start(0);
  } catch {
    /* audio not available — ignore */
  }
}

export function setSoundEnabled(on) {
  enabled = !!on;
  if (!enabled) pendingPlay = false;
}

export function isSoundEnabled() {
  return enabled;
}

/** Play the score "cha-ching" once for each 3+ coin cascade. */
export function playScoreSound() {
  if (!enabled) return;
  if (!ctx || ctx.state !== 'running') {
    pendingPlay = true;
    armUnlockListeners();
    return;
  }
  if (!buffer) {
    pendingPlay = true;
    preload(ctx);
    return;
  }
  playBuffer(ctx, buffer);
}

armUnlockListeners();
