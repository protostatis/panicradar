const DefiSignalsSection = ({ signals }) => {
  if (!signals || signals.length === 0) return null;

  return (
    <section>
      <h2 className="text-xl font-bold text-slate-100 mb-4">
        DeFi Signals
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {signals.map((signal, i) => (
          <div
            key={i}
            className="bg-purple-900/10 rounded-xl border border-purple-500/20 p-5 hover:border-purple-500/40 transition-colors"
          >
            <h3 className="text-sm font-semibold text-purple-300 mb-2 leading-snug">
              {signal.headline}
            </h3>
            <p className="text-slate-400 text-sm leading-relaxed mb-2">
              {signal.why_interesting}
            </p>
            <span className="text-xs text-slate-600 font-mono">{signal.source}</span>
          </div>
        ))}
      </div>
    </section>
  );
};

export default DefiSignalsSection;
