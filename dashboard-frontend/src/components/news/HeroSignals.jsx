const HeroSignals = ({ hooks }) => {
  if (!hooks || hooks.length === 0) return null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {hooks.map((hook, i) => (
        <div
          key={i}
          className="relative bg-gradient-to-b from-green-900/20 to-slate-800/30 rounded-xl border border-green-500/30 p-6 hover:border-green-500/50 transition-colors"
        >
          {/* Number badge */}
          <div className="absolute -top-3 -left-2 w-7 h-7 rounded-full bg-green-500 flex items-center justify-center">
            <span className="text-slate-900 text-sm font-bold">{i + 1}</span>
          </div>

          {/* Hook text */}
          <p className="text-slate-200 text-sm leading-relaxed mt-1">
            {hook}
          </p>
        </div>
      ))}
    </div>
  );
};

export default HeroSignals;
