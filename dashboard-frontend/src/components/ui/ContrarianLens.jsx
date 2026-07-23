import { useMemo } from 'react';
import { tone, categoryToTone } from './tones';

/**
 * ContrarianLens — PanicRadar's signature component.
 *
 * Renders the core differentiator as an instrument readout: how a RAW crowd
 * signal is transformed by the Bayesian model into a volatility readout.
 *
 *   RAW crowd  →  RELIABILITY  →  MODEL (momentum/inverted)  →  READOUT
 *
 * This embodies "no black boxes": every signal shows what changed, against
 * what baseline, whether any source was inverted, and the horizon it concerns.
 *
 * Build it from a belief object via `lensFromBelief`, or pass `stages` directly.
 */
/* eslint-disable react-refresh/only-export-components */

const Arrow = () => (
  <div className="flex items-center px-1 text-slate-600" aria-hidden="true">
    <span className="h-px w-4 bg-slate-700 sm:w-6" />
    <span className="-ml-px text-[0.6rem]">{'\u25B6'}</span>
  </div>
);

const Stage = ({ kicker, value, toneKey, mono = false }) => {
  const t = tone(toneKey);
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1">
      <span className="text-[0.6rem] font-semibold uppercase tracking-[0.18em] text-slate-500">
        {kicker}
      </span>
      <span
        className={`flex items-center gap-1.5 text-sm font-semibold leading-tight ${t.text} ${mono ? 'radar-tabular' : ''}`.trim()}
      >
        <span aria-hidden="true" className="text-[0.6rem]">{t.glyph}</span>
        <span className="truncate">{value}</span>
      </span>
    </div>
  );
};

/**
 * Build lens stages from a Bayesian belief object.
 * belief: { source, type_label, accuracy, total_crawls, correlation, ... }
 * rawLabel: the current crowd sentiment label for this source (e.g. "Euphoric")
 */
export const lensFromBelief = (belief, rawLabel = 'Bullish') => {
  const acc = belief?.accuracy ?? null;
  const accPct = acc !== null ? `${Math.round(acc * 100)}%` : '—';
  const inverted = belief?.type_label === 'Contrarian';
  const momentum = belief?.type_label === 'Momentum';
  const reliable = acc !== null && acc >= 0.5;

  return {
    raw: {
      toneKey: categoryToTone(rawLabel),
      value: rawLabel,
    },
    reliability: {
      toneKey: reliable ? 'bull' : 'warn',
      value: `${accPct} reliable`,
    },
    model: {
      toneKey: inverted ? 'bear' : momentum ? 'bull' : 'neutral',
      value: inverted ? 'Inverted' : momentum ? 'Momentum' : 'Neutral',
    },
    readout: {
      toneKey: inverted ? 'bull' : momentum ? 'bear' : 'neutral',
      value: inverted ? 'Fade the crowd' : momentum ? 'Follow the signal' : 'Low weight',
    },
  };
};

const ContrarianLens = ({
  source,
  raw,
  reliability,
  model,
  readout,
  stages,
  horizon,
  footnote,
  className = '',
}) => {
  const data = useMemo(() => {
    if (stages) return stages;
    return { raw, reliability, model, readout };
  }, [stages, raw, reliability, model, readout]);

  const stageList = [
    { kicker: 'Raw crowd', ...data.raw },
    { kicker: 'Reliability', ...data.reliability },
    { kicker: 'Model', ...data.model },
    { kicker: 'Readout', ...data.readout },
  ];

  return (
    <div className={`radar-panel radar-panel--accent p-5 sm:p-6 ${className}`.trim()}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <span className="radar-kicker radar-kicker--tick">Contrarian lens</span>
        {source && (
          <span className="radar-chip px-2.5 py-1 text-xs">
            <span className="text-slate-500">source</span>
            <span className="font-mono text-slate-300">{source}</span>
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-stretch gap-y-3">
        {stageList.map((s, i) => (
          <div key={s.kicker} className="contents">
            <Stage kicker={s.kicker} value={s.value} toneKey={s.toneKey} mono={s.mono} />
            {i < stageList.length - 1 && <Arrow />}
          </div>
        ))}
      </div>

      {(horizon || footnote) && (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-slate-800 pt-3 text-xs text-slate-500">
          {horizon && (
            <span>
              <span className="text-slate-600">Horizon</span>{' '}
              <span className="radar-tabular text-slate-400">{horizon}</span>
            </span>
          )}
          {footnote && <span className="text-slate-500">{footnote}</span>}
        </div>
      )}
    </div>
  );
};

export default ContrarianLens;
