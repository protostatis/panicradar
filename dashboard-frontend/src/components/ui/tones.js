/**
 * Tone system — colourblind-safe semantic encoding.
 * Every tone carries a SHAPE/GLYPH + LABEL alongside colour, so meaning never
 * depends on hue alone (WCAG 1.4.1). All sentiment UI routes through here.
 *
 * Tones are deliberately restrained: ~90% of the UI is neutral; semantic
 * colour appears only where it carries information.
 *
 * Each entry: { text, border, chip, dot, glyph, label }
 *  - glyph is a unicode shape redundant with colour
 */

export const TONES = {
  bull: {
    label: 'Bullish',
    text: 'text-green-400',
    border: 'border-green-400/50',
    chipBg: 'bg-green-400/10',
    dot: 'bg-green-400',
    glyph: '\u25B2', // ▲ up triangle
  },
  bear: {
    label: 'Bearish',
    text: 'text-red-400',
    border: 'border-red-400/50',
    chipBg: 'bg-red-400/10',
    dot: 'bg-red-400',
    glyph: '\u25BC', // ▼ down triangle
  },
  warn: {
    label: 'Elevated',
    text: 'text-amber-400',
    border: 'border-amber-400/50',
    chipBg: 'bg-amber-400/10',
    dot: 'bg-amber-400',
    glyph: '\u25C6', // ◆ diamond
  },
  danger: {
    label: 'Extreme',
    text: 'text-orange-400',
    border: 'border-orange-400/50',
    chipBg: 'bg-orange-400/10',
    dot: 'bg-orange-400',
    glyph: '\u25CF', // ● filled circle
  },
  accent: {
    label: 'Live',
    text: 'text-cyan-400',
    border: 'border-cyan-400/50',
    chipBg: 'bg-cyan-400/10',
    dot: 'bg-cyan-400',
    glyph: '\u25C6',
  },
  neutral: {
    label: 'Stable',
    text: 'text-slate-300',
    border: 'border-slate-500/40',
    chipBg: 'bg-slate-500/10',
    dot: 'bg-slate-400',
    glyph: '\u25AC', // ▬ block
  },
};

export const tone = (key) => TONES[key] || TONES.neutral;

/** Map a numeric sentiment score (-1..1) to a tone + arrow. */
export const scoreToTone = (score, thresholds = { up: 0.1, down: -0.1 }) => {
  if (score === null || score === undefined || Number.isNaN(score)) return 'neutral';
  if (score >= thresholds.up) return 'bull';
  if (score <= thresholds.down) return 'bear';
  return 'neutral';
};

/** Map a 0-100 panic/volatility score to a tone. */
export const levelToTone = (score) => {
  if (score >= 60) return 'danger';
  if (score >= 40) return 'warn';
  if (score >= 20) return 'neutral';
  return 'bull'; // calm reads as "good"
};

/** Map a category string (from API) to a tone. */
export const categoryToTone = (cat) => {
  const c = String(cat || '').toLowerCase();
  if (c.includes('greed') || c.includes('euphor') || c.includes('momentum') || c.includes('bull')) return 'bull';
  if (c.includes('fear') || c.includes('panic') || c.includes('contrarian') || c.includes('bear')) return 'bear';
  if (c.includes('high') || c.includes('extreme') || c.includes('elevated')) return 'warn';
  return 'neutral';
};
