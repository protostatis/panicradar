import Panel from './ui/Panel';
import { tone } from './ui/tones';

const PCT_MAX = 100;

const GAUGE_DEFS = [
  {
    key: 'fear',
    label: 'Explicit fear phrases',
    tooltip: 'Posts containing literal panic/capitulation language (e.g. "panic sell", "it\'s over")',
    toneKey: 'bear',
    glyph: '\u25BC',
  },
  {
    key: 'euphoria',
    label: 'Explicit euphoria phrases',
    tooltip: 'Posts containing literal moon/FOMO language (e.g. "to the moon", "buy the dip")',
    toneKey: 'bull',
    glyph: '\u25B2',
  },
  {
    key: 'warning',
    label: 'Warning/scam phrases',
    tooltip: 'Posts containing scam alerts and exchange complaints (e.g. "scam", "withdrawal freeze")',
    toneKey: 'accent',
    glyph: '\u25C6',
  },
];

const GaugeBar = ({ label, value, toneKey, glyph, tooltip }) => {
  const t = tone(toneKey);
  const pct = Math.min(100, Math.max(0, (value || 0) * 100));
  const widthPct = (pct / PCT_MAX) * 100;
  return (
    <div title={tooltip}>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="inline-flex items-center gap-1.5 text-sm text-slate-300"><span aria-hidden="true" className={`text-[0.6rem] ${t.text}`}>{glyph}</span>{label}</span>
        <span className="radar-tabular text-sm font-medium text-slate-200">{(value || 0).toFixed(1)}%</span>
      </div>
      <div className="relative h-2.5 overflow-hidden rounded-full bg-slate-800">
        <span className="absolute left-1/4 top-0 h-full w-px bg-slate-700/70" aria-hidden="true" />
        <span className="absolute left-1/2 top-0 h-full w-px bg-slate-700/70" aria-hidden="true" />
        <span className="absolute left-3/4 top-0 h-full w-px bg-slate-700/70" aria-hidden="true" />
        <div className={`h-full rounded-full ${t.dot} transition-[width] duration-500`} style={{ width: `${widthPct}%` }} role="progressbar" aria-valuenow={Number((value || 0).toFixed(1))} aria-valuemin={0} aria-valuemax={100} aria-label={label} />
      </div>
    </div>
  );
};

const CrowdGauges = ({ fearIndex, euphoriaIndex, activityLevel, explicitFearPhraseRate, explicitEuphoriaPhraseRate, warningScamPhraseRate }) => {
  // Accept both new and deprecated prop names
  const fear = explicitFearPhraseRate ?? fearIndex ?? 0;
  const euphoria = explicitEuphoriaPhraseRate ?? euphoriaIndex ?? 0;
  const warning = warningScamPhraseRate ?? activityLevel ?? 0;

  const values = [
    { ...GAUGE_DEFS[0], value: fear },
    { ...GAUGE_DEFS[1], value: euphoria },
    { ...GAUGE_DEFS[2], value: warning },
  ];

  const maxVal = Math.max(fear, euphoria, warning);
  const dominant =
    fear === euphoria && euphoria === warning
      ? 'Balanced'
      : fear >= euphoria && fear >= warning
        ? 'Fear'
        : euphoria >= fear && euphoria >= warning
          ? 'Euphoria'
          : 'Warning';
  const dominantTone = { Fear: 'bear', Euphoria: 'bull', Warning: 'accent', Balanced: 'neutral' }[dominant];

  return (
    <Panel pad="md">
      <div className="mb-5 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-100">Explicit phrase detection</h3>
        <span className={`text-sm font-medium ${tone(dominantTone).text}`}>{dominant}</span>
      </div>
      <div className="space-y-4">
        {values.map((g) => (
          <GaugeBar key={g.key} label={g.label} value={g.value} toneKey={g.toneKey} glyph={g.glyph} tooltip={g.tooltip} />
        ))}
      </div>
      <p className="mt-5 text-xs text-slate-500">
        Percentage of posts containing literal trigger phrases. These are high-precision but low-recall — 91.8% of posts register none. Not a psychological measurement.
      </p>
    </Panel>
  );
};

export default CrowdGauges;
