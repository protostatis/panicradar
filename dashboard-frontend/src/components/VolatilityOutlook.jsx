import Panel from './ui/Panel';
import { tone } from './ui/tones';

const VolatilityOutlook = ({ volatilityState, sentimentState }) => {
  const isExtreme = sentimentState === 'Bullish' || sentimentState === 'Bearish';
  const outlook = () => {
    if (volatilityState === 'High' || volatilityState === 'Extreme') return { toneKey: 'danger', title: 'High volatility detected', message: isExtreme ? 'Extreme sentiment combined with high volatility suggests potential for significant price moves.' : 'Elevated volatility detected. Consider position sizing carefully.' };
    if (isExtreme) return { toneKey: 'warn', title: 'Extreme sentiment', message: sentimentState === 'Bullish' ? 'Strong bullish sentiment detected. Historically, extreme optimism can precede corrections.' : 'Strong bearish sentiment detected. Historically, extreme pessimism can mark bottoms.' };
    return { toneKey: 'neutral', title: 'Normal conditions', message: 'Sentiment and volatility are within normal ranges.' };
  };
  const o = outlook(), t = tone(o.toneKey);
  return (<Panel pad="md"><div className="flex items-center gap-2 mb-2"><span aria-hidden="true" className={`text-sm ${t.text}`}>{t.glyph}</span><h3 className="text-base font-semibold text-slate-100">{o.title}</h3></div><p className="text-sm leading-relaxed text-slate-400">{o.message}</p><p className="mt-3 text-xs text-slate-500">Outlook reflects sentiment extremes vs realized volatility — not a price-direction forecast.</p></Panel>);
};

export default VolatilityOutlook;
