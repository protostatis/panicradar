import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { fetchTrendingSignals } from '../../api/client';
import { trackEvent, GA_EVENTS } from '../../utils/analytics';

const IntelligencePreview = () => {
  const [data, setData] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const result = await fetchTrendingSignals();
        setData(result);
      } catch {
        // Silently fail
      }
    };
    load();
  }, []);

  if (!data || !data.top_3_hooks?.length) return null;

  return (
    <Link
      to="/news"
      onClick={() => trackEvent(GA_EVENTS.NEWS_CTA_CLICK, { label: 'landing_banner' })}
      className="block -mb-14 bg-green-500/10 border border-green-500/20 rounded-lg px-4 py-2.5 hover:bg-green-500/15 transition-colors group"
    >
      <div className="flex items-center justify-center gap-3 text-xs sm:text-sm">
        <span className="relative flex h-2 w-2 shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
        </span>
        <span className="text-green-400 font-semibold uppercase tracking-wider shrink-0">
          Today
        </span>
        <span className="text-slate-400 truncate">
          {data.top_3_hooks[0]}
        </span>
        <span className="text-green-400 group-hover:text-green-300 shrink-0 hidden sm:inline">
          {'\u2192'}
        </span>
      </div>
    </Link>
  );
};

export default IntelligencePreview;
