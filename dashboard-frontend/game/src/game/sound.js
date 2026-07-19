/**
 * Sound effects. Uses the native HTMLAudioElement (no extra dependency) with
 * the bundled "cha-ching" cue from the original BlockCoined build. A new
 * Audio() is created per play so overlapping scores don't cut each other off.
 */
import chaching from '../sound/Cha-ching-sound.mp3';

let enabled = true;

export function setSoundEnabled(on) {
  enabled = !!on;
}

export function isSoundEnabled() {
  return enabled;
}

/** Play the score "cha-ching". Safe to call repeatedly; ignores failures. */
export function playScoreSound() {
  if (!enabled) return;
  try {
    const a = new Audio(chaching);
    a.volume = 0.6;
    const p = a.play();
    if (p && typeof p.catch === 'function') p.catch(() => {});
  } catch {
    /* audio not available — ignore */
  }
}
