import { tone } from './tones';

/**
 * ToneBadge — categorical sentiment badge: GLYPH + LABEL + colour.
 * Use for sentiment categories, source types, risk levels.
 *
 * props:
 *  - toneKey: one of TONES keys (bull|bear|warn|danger|accent|neutral)
 *  - label: override label (defaults to tone label)
 *  - glyph: override glyph (defaults to tone glyph); set false to hide
 *  - size: 'sm' | 'md'
 *  - live: render an animated live dot instead of the static glyph
 */
const ToneBadge = ({
  toneKey = 'neutral',
  label,
  glyph,
  size = 'sm',
  live = false,
  className = '',
}) => {
  const t = tone(toneKey);
  const sizing =
    size === 'md'
      ? 'px-2.5 py-1 text-xs'
      : 'px-2 py-0.5 text-[0.7rem]';

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-semibold uppercase tracking-[0.14em] ${t.chipBg} ${t.border} ${t.text} ${sizing} ${className}`.trim()}
    >
      {live ? (
        <span className={`radar-live-dot ${toneKey === 'warn' || toneKey === 'danger' ? 'radar-live-dot--stale' : ''}`} aria-hidden="true" />
      ) : (
        glyph !== false && (
          <span aria-hidden="true" className="text-[0.6rem] leading-none">
            {glyph ?? t.glyph}
          </span>
        )
      )}
      {label ?? t.label}
    </span>
  );
};

export default ToneBadge;
