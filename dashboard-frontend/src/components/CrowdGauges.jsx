import { useMemo } from 'react';

const GaugeBar = ({ label, value, normalizedValue, color }) => {
  const percentage = Math.min(100, Math.max(0, normalizedValue * 100));

  return (
    <div className="mb-3">
      <div className="flex justify-between text-sm mb-1">
        <span className="text-slate-400">{label}</span>
        <span className="text-slate-300">{(value * 100).toFixed(1)}%</span>
      </div>
      <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${color} transition-all duration-500`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
};

const CrowdGauges = ({ fearIndex, euphoriaIndex, activityLevel }) => {
  // Normalize values relative to max for better visualization
  const normalized = useMemo(() => {
    const values = [fearIndex || 0, euphoriaIndex || 0, activityLevel || 0];
    const maxVal = Math.max(...values, 0.001); // Avoid division by zero

    return {
      fear: (fearIndex || 0) / maxVal,
      euphoria: (euphoriaIndex || 0) / maxVal,
      activity: (activityLevel || 0) / maxVal,
    };
  }, [fearIndex, euphoriaIndex, activityLevel]);

  // Determine dominant signal
  const dominant = useMemo(() => {
    const fear = fearIndex || 0;
    const euphoria = euphoriaIndex || 0;
    const activity = activityLevel || 0;

    if (fear > euphoria && fear > activity) return 'Fear';
    if (euphoria > fear && euphoria > activity) return 'Euphoria';
    if (activity > fear && activity > euphoria) return 'Activity';
    return 'Balanced';
  }, [fearIndex, euphoriaIndex, activityLevel]);

  const getDominantColor = () => {
    switch (dominant) {
      case 'Fear':
        return 'text-red-400';
      case 'Euphoria':
        return 'text-green-400';
      case 'Activity':
        return 'text-blue-400';
      default:
        return 'text-slate-300';
    }
  };

  return (
    <div className="radar-panel p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-slate-200">
          Crowd Psychology
        </h3>
        <span className={`text-sm font-medium ${getDominantColor()}`}>
          {dominant}
        </span>
      </div>
      <GaugeBar
        label="Fear"
        value={fearIndex || 0}
        normalizedValue={normalized.fear}
        color="bg-gradient-to-r from-orange-500 to-red-500"
      />
      <GaugeBar
        label="Euphoria"
        value={euphoriaIndex || 0}
        normalizedValue={normalized.euphoria}
        color="bg-gradient-to-r from-green-500 to-emerald-400"
      />
      <GaugeBar
        label="Activity"
        value={activityLevel || 0}
        normalizedValue={normalized.activity}
        color="bg-gradient-to-r from-blue-500 to-purple-500"
      />
      <p className="text-xs text-slate-500 mt-4">
        Bars normalized relative to max. Values show raw %.
      </p>
    </div>
  );
};

export default CrowdGauges;
