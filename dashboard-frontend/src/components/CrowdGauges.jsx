import Panel from './ui/Panel';
import { tone } from './ui/tones';

const PCT_MAX = 100;

const GaugeBar = ({ label, value, toneKey, glyph }) => {
  const t = tone(toneKey);
  const pct = Math.min(100, Math.max(0, (value || 0) * 100));
  const widthPct = (pct / PCT_MAX) * 100;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="inline-flex items-center gap-1.5 text-sm text-slate-300"><span aria-hidden="true" className={`text-[0.6rem] ${t.text}`}>{glyph}</span>{label}</span>
        <span className="radar-tabular text-sm font-medium text-slate-200">{(value || 0).toFixed(1)}%</span>
      </div>
      <div className="relative h-2.5 overflow-hidden rounded-full bg-slate-800">
        <span className="absolute left-1/4 top-0 h-full w-px bg-slate-700/70" aria-hidden="true" />
        <span className="absolute left-1/2 top-0 h-full w-px bg-slate-700/70" aria-hidden="true" />
        <span className="absolute left-3/4 top-0 h-full w-px bg-slate-700/70" aria-hidden="true" />
        <div className={`h-full rounded-full ${t.dot} transition-[width] duration-500`} style={{ width: `${widthPct}%` }} role="progressbar" aria-valuenow={Number((value || 0).toFixed(1))} aria-valuemin={0} aria-valuemax={100} aria-label={`${label} index`} />
      </div>
    </div>
  );
};

const CrowdGauges = ({ fearIndex, euphoriaIndex, activityLevel }) => {
  const fear = fearIndex || 0, euphoria = euphoriaIndex || 0, activity = activityLevel || 0;
  const dominant = fear === euphoria && euphoria === activity ? 'Balanced' : fear >= euphoria && fear >= activity ? 'Fear' : euphoria >= fear && euphoria >= activity ? 'Euphoria' : 'Activity';
  const dominantTone = { Fear: 'bear', Euphoria: 'bull', Activity: 'accent', Balanced: 'neutral' }[dominant];
  return (
    <Panel pad="md">
      <div className="mb-5 flex items-center justify-between"><h3 className="text-base font-semibold text-slate-100">Crowd psychology</h3><span className={`text-sm font-medium ${tone(dominantTone).text}`}>{dominant}</span></div>
      <div className="space-y-4">
        <GaugeBar label="Fear" value={fear} toneKey="bear" glyph={"\u25BC"} />
        <GaugeBar label="Euphoria" value={euphoria} toneKey="bull" glyph={"\u25B2"} />
        <GaugeBar label="Activity" value={activity} toneKey="accent" glyph={"\u25C6"} />
      </div>
      <p className="mt-5 text-xs text-slate-500">All indices on a fixed 0–100% scale. Raw values shown.</p>
    </Panel>
  );
};

export default CrowdGauges;
