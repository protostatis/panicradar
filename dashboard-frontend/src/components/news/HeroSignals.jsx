import { useState } from 'react';
import { trackEvent, GA_EVENTS } from '../../utils/analytics';

const HeroSignals = ({ hooks }) => {
  const [copiedIndex, setCopiedIndex] = useState(null);

  if (!hooks || hooks.length === 0) return null;

  const handleShare = async (hook, index) => {
    const url = `${window.location.origin}/news?utm_source=share&utm_medium=signal_card&utm_campaign=daily_briefing`;
    const text = `PanicRadar signal ${index + 1}: ${hook}`;

    trackEvent(GA_EVENTS.NEWS_SHARE_CLICK, {
      label: `top_signal_${index + 1}`,
      title: hook,
    });

    if (navigator.share) {
      try {
        await navigator.share({ title: 'PanicRadar daily signal', text, url });
        return;
      } catch {
        // Fall back to clipboard if the native share sheet is dismissed.
      }
    }

    try {
      await navigator.clipboard.writeText(`${text}\n${url}`);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 1800);
    } catch {
      setCopiedIndex(null);
    }
  };

  return (
    <section className="radar-panel overflow-hidden p-5 sm:p-6">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_0%,rgba(16,185,129,0.20),transparent_34%),radial-gradient(circle_at_90%_10%,rgba(14,165,233,0.14),transparent_32%)]" />
      <div className="absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.04)_1px,transparent_1px)] bg-[size:28px_28px] opacity-50" />

      <div className="relative">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between mb-4">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.28em] text-emerald-300">
              Today's 3 Crypto Risk Signals
            </div>
            <p className="mt-1.5 max-w-2xl text-sm text-slate-400">
              The highest-signal stories from today's scan, packaged for sharing before the crowd narrative hardens.
            </p>
          </div>
          <div className="rounded-full border border-slate-700/80 bg-slate-900/80 px-3 py-1 text-xs font-mono text-slate-400">
            Share-ready briefing
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {hooks.map((hook, i) => (
            <article
              key={i}
              className="group relative min-h-36 overflow-hidden rounded-2xl border border-slate-700/70 bg-slate-900/75 p-4 transition-all duration-300 hover:-translate-y-0.5 hover:border-emerald-400/50 hover:bg-slate-900"
            >
              <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-emerald-400 via-cyan-300 to-transparent opacity-70" />
              <div className="absolute -right-10 -top-10 h-28 w-28 rounded-full bg-emerald-400/10 blur-2xl transition-opacity group-hover:opacity-80" />

              <div className="relative flex h-full flex-col justify-between gap-4">
                <div>
                  <div className="mb-3 flex items-center justify-between">
                    <span className="font-mono text-2xl font-semibold leading-none text-slate-700">
                      0{i + 1}
                    </span>
                    <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.22em] text-emerald-300">
                      Signal
                    </span>
                  </div>
                  <p className="text-sm font-semibold leading-snug text-slate-100 sm:text-base">
                    {hook}
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => handleShare(hook, i)}
                  className="radar-button-ghost w-fit px-3 py-1.5 text-xs"
                  aria-label={`Share signal ${i + 1}`}
                >
                  {copiedIndex === i ? 'Copied link' : 'Share signal'}
                </button>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
};

export default HeroSignals;
