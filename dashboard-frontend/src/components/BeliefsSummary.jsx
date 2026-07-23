import { Link } from 'react-router-dom';
import Panel from './ui/Panel';
import ToneBadge from './ui/ToneBadge';

const BeliefsSummary = ({ beliefs, lastUpdate }) => {
  if (!beliefs || beliefs.length === 0) return null;
  const activeBeliefs = beliefs.filter((b) => b.total_crawls >= 20);
  const momentum = activeBeliefs.filter((b) => b.type_label === 'Momentum').sort((a, b) => (b.accuracy || 0) - (a.accuracy || 0)).slice(0, 3);
  const contrarian = activeBeliefs.filter((b) => b.type_label === 'Contrarian').sort((a, b) => (a.accuracy || 1) - (b.accuracy || 1)).slice(0, 3);
  const formatSourceName = (source) => source.replace('reddit_', 'r/').replace('4chan_', '/').replace(/_/g, '');
  const SourceRow = ({ belief }) => (<div className="flex items-center justify-between gap-2 rounded-lg border border-slate-700/50 bg-slate-900/50 px-3 py-2"><span className="truncate text-sm font-medium text-slate-200">{formatSourceName(belief.source)}</span><span className="radar-tabular text-sm font-semibold text-slate-200">{belief.accuracy !== null ? `${(belief.accuracy * 100).toFixed(0)}%` : 'N/A'}</span></div>);
  return (
    <Panel pad="md">
      <div className="mb-4 flex items-center justify-between"><h3 className="text-base font-semibold text-slate-100">Bayesian model beliefs</h3><Link to="/beliefs" className="text-sm text-cyan-300 transition-colors hover:text-cyan-200">View all →</Link></div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div><div className="mb-2"><ToneBadge toneKey="bull" label="Top momentum" glyph={false} /></div><div className="space-y-2">{momentum.length > 0 ? momentum.map((b) => <SourceRow key={b.source} belief={b} />) : <p className="text-sm text-slate-500">No momentum sources yet</p>}</div></div>
        <div><div className="mb-2"><ToneBadge toneKey="bear" label="Top contrarian" glyph={false} /></div><div className="space-y-2">{contrarian.length > 0 ? contrarian.map((b) => <SourceRow key={b.source} belief={b} />) : <p className="text-sm text-slate-500">No contrarian sources yet</p>}</div></div>
      </div>
      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-slate-800 pt-4 text-xs text-slate-500">
        <span><span className="text-slate-300">{activeBeliefs.length}</span> active sources</span>
        <span><span className="text-green-300">{beliefs.filter((b) => b.type_label === 'Momentum').length}</span> momentum</span>
        <span><span className="text-red-300">{beliefs.filter((b) => b.type_label === 'Contrarian').length}</span> contrarian</span>
        {lastUpdate && <span className="ml-auto">Updated: <span className="radar-tabular text-slate-400">{new Date(lastUpdate).toLocaleDateString()}</span></span>}
      </div>
    </Panel>
  );
};

export default BeliefsSummary;
