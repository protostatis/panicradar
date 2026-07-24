import { tone } from '../ui/tones';
import ToneBadge from '../ui/ToneBadge';

/**
 * Map the backend "surprise_score" (high|medium|low) into the colourblind-safe
 * tone system, so meaning never depends on hue alone (glyph + label carry it).
 */
const SURPRISE_TO_TONE = {
  high: { key: 'danger', label: 'High impact' },
  medium: { key: 'warn', label: 'Watch' },
  low: { key: 'neutral', label: 'Context' },
};

const SURPRISE_BORDER = {
  high: 'border-l-red-500',
  medium: 'border-l-amber-500',
  low: 'border-l-slate-500',
};

/** Tone-matched hover glow + border lift, so each card reacts in its own colour. */
const SURPRISE_HOVER = {
  high: 'hover:border-red-500/50 hover:shadow-[0_16px_44px_-16px_rgba(239,68,68,0.45)]',
  medium: 'hover:border-amber-500/50 hover:shadow-[0_16px_44px_-16px_rgba(245,158,11,0.30)]',
  low: 'hover:border-slate-400/40 hover:shadow-[0_16px_44px_-16px_rgba(148,163,184,0.22)]',
};

/** Humanize an arbitrary engagement key (e.g. reddit_upvotes -> "Reddit upvotes"). */
const humanizeKey = (key) =>
  String(key)
    .replace(/_/g, ' ')
    .replace(/^\w/, (c) => c.toUpperCase());

const compactNum = (value) => {
  if (typeof value !== 'number') return String(value);
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
};

const EngagementMetrics = ({ engagement }) => {
  if (!engagement) return null;

  const metrics = Object.entries(engagement)
    .filter(([, v]) => typeof v === 'number' && v > 0)
    .slice(0, 4);

  if (metrics.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
      {metrics.map(([key, value]) => (
        <span key={key} className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="h-1 w-1 rounded-full bg-slate-600" />
          <span className="text-slate-500">{humanizeKey(key)}</span>
          <span className="radar-tabular font-medium text-slate-300">{compactNum(value)}</span>
        </span>
      ))}
    </div>
  );
};

const SourceChain = ({ source }) => {
  const nodes = source.split(/\s*[→>]\s*/).map((s) => s.trim()).filter(Boolean);
  if (nodes.length === 0) return null;

  return (
    <div className="flex items-center gap-1 flex-wrap justify-end">
      {nodes.map((node, i) => (
        <span key={i} className="inline-flex items-center">
          <span className="rounded border border-slate-700/80 bg-slate-800/60 px-2 py-0.5 font-mono text-[0.7rem] text-slate-300">
            {node}
          </span>
          {i < nodes.length - 1 && (
            <span aria-hidden="true" className="mx-1 text-xs text-slate-600">{'\u2192'}</span>
          )}
        </span>
      ))}
    </div>
  );
};

const SignalCard = ({ signal }) => {
  const level = signal.surprise_score;
  const mapping = SURPRISE_TO_TONE[level] || SURPRISE_TO_TONE.low;
  const t = tone(mapping.key);
  const borderColor = SURPRISE_BORDER[level] || 'border-l-slate-600';
  const hoverGlow = SURPRISE_HOVER[level] || SURPRISE_HOVER.low;
  const url = signal.url || signal.link;

  const cardClasses = `radar-card group border-l-2 ${borderColor} p-5 sm:p-6 transition-all duration-200 hover:-translate-y-0.5 ${hoverGlow} ${
    url ? 'cursor-pointer' : ''
  }`;

  const inner = (
    <>
      {/* Header: priority badge + source chain */}
      <div className="mb-3 flex items-start justify-between gap-3">
        <ToneBadge
          toneKey={mapping.key}
          label={mapping.label}
          title={`Surprise score: ${level}`}
        />
        <SourceChain source={signal.source} />
      </div>

      {/* Headline */}
      <h3 className="mb-2 text-base font-semibold leading-snug text-slate-100 sm:text-lg">
        {signal.headline}
      </h3>

      {/* Contrarian analysis */}
      <p className="mb-3 text-sm leading-relaxed text-slate-400">
        {signal.why_interesting}
      </p>

      {/* Content hook quote */}
      {signal.content_hook && (
        <blockquote className="mb-3 rounded-r border-l-2 border-green-500/50 bg-slate-950/50 py-2 pl-4">
          <p className="text-sm italic leading-relaxed text-slate-300">
            {signal.content_hook}
          </p>
        </blockquote>
      )}

      {/* Video hook — engagement driver previously unrendered */}
      {signal.video_hook && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-cyan-400/20 bg-cyan-400/5 px-3 py-2">
          <span aria-hidden="true" className="text-sm">{'\u25B6'}</span>
          <span className="text-sm text-cyan-200">{signal.video_hook}</span>
        </div>
      )}

      {/* Footer: discovery + engagement */}
      <div className="flex flex-col gap-2.5 border-t border-slate-700/40 pt-3">
        {signal.discovered_via && (
          <div className="text-xs text-slate-500">
            <span className="text-slate-600">Found via </span>
            <span className="font-mono text-slate-400">{signal.discovered_via}</span>
          </div>
        )}
        <EngagementMetrics engagement={signal.engagement} />
        {url && (
          <span className={`inline-flex items-center gap-1 text-xs font-medium transition-transform duration-200 group-hover:translate-x-0.5 ${t.text}`}>
            Read source
            <span aria-hidden="true">{'\u2197'}</span>
          </span>
        )}
      </div>
    </>
  );

  if (url) {
    const external = /^https?:\/\//.test(url);
    if (external) {
      return (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className={`block ${cardClasses}`}
        >
          {inner}
        </a>
      );
    }
  }

  return <article className={cardClasses}>{inner}</article>;
};

export default SignalCard;
