import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { tone } from './tones';
import { levelToTone } from './tones';

/**
 * StatTile — colourblind-safe metric tile (replaces MetricCard).
 * Colour is conveyed by a left accent hairline + tone glyph + tone text,
 * so a colourblind user still gets the state from the glyph/label.
 *
 * props:
 *  - title, value, subtitle
 *  - toneKey: explicit tone, OR pass `score` (0-100) to derive automatically
 *  - href: internal path or external URL (whole tile becomes a link)
 *  - footer: small node under the value
 */
const StatTile = ({ title, value, subtitle, toneKey, score, href, footer }) => {
  const key = toneKey ?? (typeof score === 'number' ? levelToTone(score) : 'neutral');
  const t = useMemo(() => tone(key), [key]);

  const inner = (
    <>
      <span
        aria-hidden="true"
        className={`absolute left-0 top-4 bottom-4 w-[2px] rounded-full ${t.dot}`}
      />
      <div className="pl-3">
        <div className="flex items-center gap-2">
          <span aria-hidden="true" className={`text-[0.6rem] leading-none ${t.text}`}>{t.glyph}</span>
          <h3 className="text-[0.7rem] font-semibold uppercase tracking-[0.18em] text-slate-400">
            {title}
          </h3>
        </div>
        <div className="radar-tabular mt-2 text-3xl font-semibold leading-none text-slate-50">
          {value ?? '—'}
        </div>
        {subtitle && <div className="mt-1.5 text-sm text-slate-400">{subtitle}</div>}
        {footer && <div className="mt-2">{footer}</div>}
      </div>
    </>
  );

  const cls = `radar-card relative block w-full border ${t.border} p-4 transition-transform duration-150 hover:-translate-y-0.5`;

  if (href) {
    if (href.startsWith('/')) {
      return (
        <Link to={href} className={`${cls} cursor-pointer`}>
          {inner}
        </Link>
      );
    }
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={`${cls} cursor-pointer`}>
        {inner}
      </a>
    );
  }

  return <div className={cls}>{inner}</div>;
};

export default StatTile;
