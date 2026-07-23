import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { tone, levelToTone, categoryToTone } from './ui/tones';

const typeToTone = (type) => { switch (type) { case 'bullish': case 'greed': case 'low': return 'bull'; case 'bearish': case 'fear': case 'high': return 'bear'; case 'neutral': case 'moderate': return 'warn'; default: return 'neutral'; } };

const MetricCard = ({ title, value, subtitle, type = 'default', score, category, href }) => {
  const toneKey = useMemo(() => { if (type !== 'default') return typeToTone(type); if (typeof score === 'number') return levelToTone(score); if (category) return categoryToTone(category); return 'neutral'; }, [type, score, category]);
  const t = tone(toneKey);
  const content = (<><div className="flex items-center gap-2"><span aria-hidden="true" className={`text-[0.6rem] leading-none ${t.text}`}>{t.glyph}</span><h3 className="text-[0.7rem] font-semibold uppercase tracking-[0.18em] text-slate-400">{title}</h3></div><div className="radar-tabular mt-2 text-3xl font-semibold leading-none text-slate-50">{value}</div>{subtitle && <div className="mt-1.5 text-sm text-slate-400">{subtitle}</div>}</>);
  const cls = `radar-card relative block w-full border-l-2 ${t.border} p-4 transition-transform duration-150 hover:-translate-y-0.5`;
  if (href) { if (href.startsWith('/')) return <Link to={href} className={`${cls} cursor-pointer`}>{content}</Link>; return <a href={href} target="_blank" rel="noopener noreferrer" className={`${cls} cursor-pointer`}>{content}</a>; }
  return <div className={cls}>{content}</div>;
};

export default MetricCard;
