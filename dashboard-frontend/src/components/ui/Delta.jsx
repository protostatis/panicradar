import { tone } from './tones';

/**
 * Delta — colourblind-safe change indicator for a numeric value.
 * Renders: ARROW + signed number, coloured by direction. Never hue alone.
 *
 * props:
 *  - value: number
 *  - suffix: string (e.g. '%', 'x')
 *  - decimals: number (default 1)
 *  - invert: boolean — for metrics where down is good (e.g. volatility)
 *  - className
 */
const formatDelta = (value, suffix, decimals) => {
  const sign = value > 0 ? '+' : '';
  return `${sign}${Number(value).toFixed(decimals)}${suffix || ''}`;
};

const Delta = ({ value, suffix = '', decimals = 1, invert = false, className = '' }) => {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <span className={`text-slate-500 ${className}`.trim()}>—</span>;
  }

  let key = 'neutral';
  if (value > 0) key = invert ? 'bear' : 'bull';
  else if (value < 0) key = invert ? 'bull' : 'bear';

  const t = tone(key);
  const arrow = value > 0 ? '\u25B2' : value < 0 ? '\u25BC' : '\u25AC';

  return (
    <span
      className={`radar-tabular inline-flex items-center gap-1 font-medium ${t.text} ${className}`.trim()}
      title={`${t.label} ${formatDelta(value, suffix, decimals)}`}
    >
      <span aria-hidden="true">{arrow}</span>
      {formatDelta(value, suffix, decimals)}
    </span>
  );
};

export default Delta;
