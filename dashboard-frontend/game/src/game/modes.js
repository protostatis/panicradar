/**
 * Game mode constants and metadata.
 * Synchronised from protostatis/blockcoined2 (ff4d798).
 */

export const MODE = {
  SELF: 'self',
  PVP: 'pvp',
  AGENT: 'agent',
  TUTORIAL: 'tutorial',
};

export const MODE_META = {
  [MODE.SELF]: {
    label: 'Solo Play',
    blurb: 'Match coins endlessly — no opponent, no timer, just puzzles.',
    transport: 'local',
  },
  [MODE.PVP]: {
    label: 'Versus (PvP)',
    blurb: 'Challenge another player over WebSocket — skill vs skill.',
    transport: 'ws',
  },
  [MODE.AGENT]: {
    label: 'Versus AI Agent',
    blurb: 'You vs a free OpenRouter LLM. Paste your API key; the agent picks its own swaps.',
    transport: 'local',
  },
  [MODE.TUTORIAL]: {
    label: 'Try the Game',
    blurb: 'Learn the basics — no pressure, no opponent, no coins at stake.',
    transport: 'local',
  },
};

/**
 * Return true if a mode is played locally (no network transport).
 */
export function isLocalMode(mode) {
  return MODE_META[mode]?.transport === 'local';
}
