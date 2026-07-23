import { useEffect, useState } from 'react';

/* eslint-disable react-refresh/only-export-components */

const MIN = 60 * 1000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

/** "Xm ago" / "Xh ago" relative label. */
export const formatAge = (ms) => {
  const a = Math.abs(ms);
  if (a < MIN) return 'just now';
  if (a < HOUR) return `${Math.floor(a / MIN)}m ago`;
  if (a < DAY) return `${Math.floor(a / HOUR)}h ago`;
  return `${Math.floor(a / DAY)}d ago`;
};

/** "14:32 UTC" clock label. */
export const formatClock = (date) =>
  date.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
  }) + ' UTC';

/**
 * FreshnessChip — real freshness semantics, not just a pulse.
 * Shows "Data as of HH:MM UTC · Xm ago" with a live dot that turns amber
 * once data exceeds `staleAfterMs`. "Live" only means inside SLA.
 *
 * props:
 *  - updatedAt: Date | ISO string | epoch ms
 *  - staleAfterMs: when the dot flips from cyan to amber (default 6m)
 *  - label: leading label (default "Data as of")
 *  - tick: recompute interval ms (default 30s)
 */
const FreshnessChip = ({
  updatedAt,
  staleAfterMs = 6 * MIN,
  label = 'Data as of',
  tick = 30 * 1000,
  className = '',
}) => {
  const [, force] = useState(0);

  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), tick);
    return () => clearInterval(id);
  }, [tick]);

  if (!updatedAt) {
    return (
      <span className={`radar-chip px-2.5 py-1 text-xs ${className}`.trim()}>
        <span className="radar-live-dot radar-live-dot--stale" aria-hidden="true" />
        <span className="text-slate-500">No timestamp</span>
      </span>
    );
  }

  const date = updatedAt instanceof Date ? updatedAt : new Date(updatedAt);
  const ageMs = Date.now() - date.getTime();
  const stale = ageMs > staleAfterMs;

  return (
    <span
      className={`radar-chip px-2.5 py-1 text-xs ${className}`.trim()}
      title={stale ? 'Data may be stale — refresh pending' : 'Within freshness SLA'}
    >
      <span className={`radar-live-dot ${stale ? 'radar-live-dot--stale' : ''}`} aria-hidden="true" />
      <span className="text-slate-400">
        {label} <span className="radar-tabular text-slate-300">{formatClock(date)}</span>
      </span>
      <span className="text-slate-600" aria-hidden="true">·</span>
      <span className={`radar-tabular ${stale ? 'text-amber-300' : 'text-slate-400'}`}>
        {formatAge(ageMs)}
      </span>
    </span>
  );
};

export default FreshnessChip;
