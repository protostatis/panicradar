import { useState, useEffect, useRef } from 'react';
import katex from 'katex';
import 'katex/dist/katex.min.css';

// --- Math rendering helpers ---
const Eq = ({ children, display = false }) => {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current) {
      katex.render(children, ref.current, {
        displayMode: display,
        throwOnError: false,
      });
    }
  }, [children, display]);
  return display ? (
    <div className="my-4 overflow-x-auto text-center" ref={ref} />
  ) : (
    <span ref={ref} />
  );
};

// --- Visualization: Source Feature Space ---
const SourceFeatureViz = () => {
  const [hovered, setHovered] = useState(null);
  // Simplified 2D projection of actual source features
  const sources = [
    { id: 'r/bitcoin', x: 180, y: 140, r: 18, color: '#f59e0b', cluster: 'main' },
    { id: 'r/cryptocurrency', x: 220, y: 165, r: 16, color: '#f59e0b', cluster: 'main' },
    { id: 'r/ethtrader', x: 260, y: 130, r: 13, color: '#8b5cf6', cluster: 'main' },
    { id: 'r/ethereum', x: 310, y: 180, r: 12, color: '#8b5cf6', cluster: 'alt' },
    { id: 'r/bitcoinbeginners', x: 400, y: 280, r: 11, color: '#10b981', cluster: 'beginner' },
    { id: 'r/coinbase', x: 430, y: 260, r: 12, color: '#10b981', cluster: 'beginner' },
    { id: 'r/cryptotax', x: 470, y: 310, r: 9, color: '#10b981', cluster: 'beginner' },
    { id: 'r/dogecoin', x: 130, y: 260, r: 11, color: '#ec4899', cluster: 'meme' },
    { id: 'r/cryptomoonshots', x: 110, y: 210, r: 10, color: '#ec4899', cluster: 'meme' },
    { id: 'r/cryptocurrencymemes', x: 80, y: 180, r: 8, color: '#ec4899', cluster: 'meme' },
    { id: 'r/solana', x: 350, y: 150, r: 10, color: '#8b5cf6', cluster: 'alt' },
    { id: 'r/defi', x: 340, y: 220, r: 9, color: '#8b5cf6', cluster: 'alt' },
    { id: 'r/cryptomarkets', x: 160, y: 200, r: 11, color: '#f59e0b', cluster: 'main' },
  ];
  const edges = [
    ['r/bitcoin', 'r/cryptocurrency', 0.9],
    ['r/bitcoin', 'r/ethtrader', 0.6],
    ['r/cryptocurrency', 'r/ethtrader', 0.5],
    ['r/bitcoinbeginners', 'r/coinbase', 0.95],
    ['r/coinbase', 'r/cryptotax', 0.55],
    ['r/dogecoin', 'r/cryptomoonshots', 0.5],
    ['r/cryptomoonshots', 'r/cryptocurrencymemes', 0.55],
    ['r/ethereum', 'r/solana', 0.5],
    ['r/ethereum', 'r/defi', 0.45],
    ['r/bitcoin', 'r/cryptomarkets', 0.5],
    ['r/cryptocurrency', 'r/cryptomarkets', 0.45],
  ];
  const getSource = (id) => sources.find(s => s.id === id);

  return (
    <div className="my-6">
      <div className="text-sm font-medium text-slate-400 mb-2 text-center">Source Similarity in Feature Space (2D projection)</div>
      <svg viewBox="0 0 560 360" className="w-full bg-slate-900/50 rounded-xl border border-slate-700">
        {/* Edges */}
        {edges.map(([a, b, w], i) => {
          const sa = getSource(a), sb = getSource(b);
          const isHovered = hovered === a || hovered === b;
          return (
            <line key={i} x1={sa.x} y1={sa.y} x2={sb.x} y2={sb.y}
              stroke={isHovered ? '#a78bfa' : '#475569'} strokeWidth={w * 3}
              strokeOpacity={isHovered ? 0.8 : 0.3} />
          );
        })}
        {/* Nodes */}
        {sources.map((s) => (
          <g key={s.id} onMouseEnter={() => setHovered(s.id)} onMouseLeave={() => setHovered(null)}
            className="cursor-pointer">
            <circle cx={s.x} cy={s.y} r={s.r}
              fill={hovered === s.id ? s.color : s.color + '80'}
              stroke={hovered === s.id ? '#fff' : s.color} strokeWidth={hovered === s.id ? 2 : 1} />
            <text x={s.x} y={s.y + s.r + 14} textAnchor="middle"
              className="text-[9px] fill-slate-400" style={{ fontSize: '9px', fill: hovered === s.id ? '#e2e8f0' : '#94a3b8' }}>
              {s.id}
            </text>
          </g>
        ))}
        {/* Legend */}
        {[['#f59e0b', 'Bitcoin/General'], ['#8b5cf6', 'Alt/DeFi'], ['#10b981', 'Beginner/Support'], ['#ec4899', 'Meme/Speculative']].map(([c, l], i) => (
          <g key={l} transform={`translate(15, ${15 + i * 18})`}>
            <circle cx={6} cy={6} r={5} fill={c + '80'} stroke={c} strokeWidth={1} />
            <text x={16} y={10} style={{ fontSize: '10px', fill: '#94a3b8' }}>{l}</text>
          </g>
        ))}
      </svg>
    </div>
  );
};

// --- Visualization: Probit Transform ---
const ProbitTransformViz = () => {
  // Generate probit curve points
  const points = [];
  for (let i = 1; i <= 99; i++) {
    const p = i / 100;
    // Approximate Phi^{-1} using rational approximation
    const a = p < 0.5 ? p : 1 - p;
    const t = Math.sqrt(-2 * Math.log(a));
    let z = t - (2.515517 + 0.802853 * t + 0.010328 * t * t) /
      (1 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t);
    if (p < 0.5) z = -z;
    points.push({ p, z });
  }
  const xScale = (p) => 60 + p * 400;
  const yScale = (z) => 150 - z * 40;

  // Example source mappings
  const examples = [
    { name: 'r/dogecoin', p: 0.60, label: '60%' },
    { name: 'r/bitcoin', p: 0.46, label: '46%' },
    { name: 'r/binance', p: 0.44, label: '44%' },
  ];

  return (
    <div className="my-6">
      <div className="text-sm font-medium text-slate-400 mb-2 text-center">Probit Link: Mapping Beta Accuracy to Gaussian Space</div>
      <svg viewBox="0 0 520 280" className="w-full bg-slate-900/50 rounded-xl border border-slate-700">
        {/* Axes */}
        <line x1={60} y1={250} x2={460} y2={250} stroke="#475569" strokeWidth={1} />
        <line x1={60} y1={20} x2={60} y2={250} stroke="#475569" strokeWidth={1} />
        {/* X axis labels */}
        {[0, 0.25, 0.5, 0.75, 1].map(v => (
          <g key={v}>
            <line x1={xScale(v)} y1={250} x2={xScale(v)} y2={255} stroke="#475569" />
            <text x={xScale(v)} y={268} textAnchor="middle" style={{ fontSize: '10px', fill: '#94a3b8' }}>{(v * 100).toFixed(0)}%</text>
          </g>
        ))}
        <text x={260} y={278} textAnchor="middle" style={{ fontSize: '10px', fill: '#64748b' }}>Beta accuracy (p = a / (a + b))</text>
        {/* Y axis labels */}
        {[-3, -2, -1, 0, 1, 2, 3].map(v => (
          <g key={v}>
            <line x1={55} y1={yScale(v)} x2={60} y2={yScale(v)} stroke="#475569" />
            <text x={50} y={yScale(v) + 4} textAnchor="end" style={{ fontSize: '10px', fill: '#94a3b8' }}>{v}</text>
          </g>
        ))}
        <text x={15} y={130} textAnchor="middle" style={{ fontSize: '10px', fill: '#64748b' }} transform="rotate(-90, 15, 130)">Probit space (z)</text>
        {/* Grid lines */}
        {[-2, -1, 0, 1, 2].map(v => (
          <line key={v} x1={60} y1={yScale(v)} x2={460} y2={yScale(v)} stroke="#334155" strokeWidth={0.5} strokeDasharray="4,4" />
        ))}
        {/* Curve */}
        <path d={points.map((pt, i) => `${i === 0 ? 'M' : 'L'}${xScale(pt.p).toFixed(1)},${yScale(pt.z).toFixed(1)}`).join(' ')}
          fill="none" stroke="#a78bfa" strokeWidth={2.5} />
        {/* Example mappings */}
        {examples.map((ex, i) => {
          const z = points.find(pt => Math.abs(pt.p - ex.p) < 0.01)?.z || 0;
          const colors = ['#10b981', '#f59e0b', '#ef4444'];
          return (
            <g key={ex.name}>
              {/* Vertical line from x-axis to curve */}
              <line x1={xScale(ex.p)} y1={250} x2={xScale(ex.p)} y2={yScale(z)}
                stroke={colors[i]} strokeWidth={1} strokeDasharray="3,3" strokeOpacity={0.6} />
              {/* Horizontal line from curve to y-axis */}
              <line x1={60} y1={yScale(z)} x2={xScale(ex.p)} y2={yScale(z)}
                stroke={colors[i]} strokeWidth={1} strokeDasharray="3,3" strokeOpacity={0.6} />
              {/* Point on curve */}
              <circle cx={xScale(ex.p)} cy={yScale(z)} r={5} fill={colors[i]} stroke="#fff" strokeWidth={1.5} />
              {/* Label */}
              <text x={xScale(ex.p) + 8} y={yScale(z) - 8} style={{ fontSize: '9px', fill: colors[i] }}>
                {ex.name} ({ex.label}) = {z.toFixed(2)}
              </text>
            </g>
          );
        })}
        {/* Curve label */}
        <text x={380} y={55} style={{ fontSize: '11px', fill: '#a78bfa', fontStyle: 'italic' }}>z = inv_probit(p)</text>
      </svg>
    </div>
  );
};

// --- Visualization: Correlated vs Independent Sampling ---
const SamplingComparisonViz = () => {
  // Box-Muller transform for normal samples
  const randn = () => {
    const u1 = Math.random(), u2 = Math.random();
    return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  };

  // Lazy initializer — runs once on mount so samples are stable
  const [samples] = useState(() => {
    const independent = [], correlated = [];
    const rho = 0.75;
    for (let i = 0; i < 80; i++) {
      independent.push({ x: randn() * 0.8, y: randn() * 0.8 });
      const z1 = randn(), z2 = randn();
      correlated.push({ x: z1 * 0.8, y: (rho * z1 + Math.sqrt(1 - rho * rho) * z2) * 0.8 });
    }
    return { independent, correlated };
  });

  // Play initial fade-in animation once
  const [animating, setAnimating] = useState(true);
  useEffect(() => {
    const timer = setTimeout(() => setAnimating(false), 500);
    return () => clearTimeout(timer);
  }, []);

  const plotSamples = (data, label, xOff) => {
    const cx = xOff + 120, cy = 130;
    const scale = 35;
    return (
      <g>
        <text x={cx} y={22} textAnchor="middle" style={{ fontSize: '11px', fill: '#e2e8f0', fontWeight: 600 }}>{label}</text>
        {/* Axes */}
        <line x1={xOff + 20} y1={cy} x2={xOff + 220} y2={cy} stroke="#334155" strokeWidth={0.5} />
        <line x1={cx} y1={30} x2={cx} y2={230} stroke="#334155" strokeWidth={0.5} />
        {/* Axis labels */}
        <text x={cx} y={248} textAnchor="middle" style={{ fontSize: '9px', fill: '#64748b' }}>r/bitcoin score</text>
        <text x={xOff + 8} y={130} textAnchor="middle" style={{ fontSize: '9px', fill: '#64748b' }} transform={`rotate(-90, ${xOff + 8}, 130)`}>r/cryptocurrency score</text>
        {/* Samples */}
        {data.map((s, i) => (
          <circle key={i} cx={cx + s.x * scale} cy={cy - s.y * scale} r={2.5}
            fill="#a78bfa" fillOpacity={animating ? 0 : 0.6}
            stroke="#a78bfa" strokeOpacity={animating ? 0 : 0.3} strokeWidth={0.5}
            style={{ transition: 'fill-opacity 0.5s, stroke-opacity 0.5s', transitionDelay: `${i * 5}ms` }} />
        ))}
      </g>
    );
  };

  return (
    <div className="my-6">
      <div className="text-sm font-medium text-slate-400 mb-2 text-center">Independent Beta Sampling vs. Correlated GP Sampling</div>
      <svg viewBox="0 0 520 265" className="w-full bg-slate-900/50 rounded-xl border border-slate-700">
        {plotSamples(samples.independent, 'Independent (standard)', 20)}
        {/* Divider */}
        <line x1={260} y1={20} x2={260} y2={240} stroke="#475569" strokeWidth={1} strokeDasharray="4,4" />
        <text x={260} y={258} textAnchor="middle" style={{ fontSize: '9px', fill: '#64748b' }}>rho = 0.75 correlation</text>
        {plotSamples(samples.correlated, 'Correlated (GP posterior)', 280)}
      </svg>
      <button onClick={() => window.location.reload()}
        className="mt-2 mx-auto block px-3 py-1 text-xs bg-purple-500/20 text-purple-300 rounded hover:bg-purple-500/30 transition-colors border border-purple-500/30">
        Regenerate
      </button>
    </div>
  );
};

// --- Visualization: GP Update Flow ---
const GPUpdateFlowViz = () => {
  const [step, setStep] = useState(0);
  const steps = [
    { label: 'Prior', desc: 'GP kernel defines source correlations', color: '#475569' },
    { label: 'Observe', desc: 'r/bitcoin accuracy = 48% (500 crawls)', color: '#f59e0b' },
    { label: 'Posterior', desc: 'Similar sources shift toward r/bitcoin', color: '#a78bfa' },
    { label: 'Sample', desc: 'Draw correlated Thompson samples', color: '#10b981' },
  ];

  const sources = [
    { name: 'r/bitcoin', x: 80 },
    { name: 'r/cryptocurrency', x: 190 },
    { name: 'r/ethtrader', x: 300 },
    { name: 'r/cryptotax', x: 410 },
  ];
  const similarity = [1.0, 0.8, 0.5, 0.1]; // to r/bitcoin

  // Prior: all centered at 0.5
  const prior = [0.5, 0.5, 0.5, 0.5];
  // After observing r/bitcoin at 0.48
  const posterior = [0.48, 0.484, 0.49, 0.499];
  // Thompson samples
  const sampled = [0.51, 0.52, 0.47, 0.53];

  const getY = (val) => 40 + (1 - val) * 160; // 0.3 -> bottom, 0.7 -> top
  const getBarVal = (srcIdx) => {
    if (step === 0) return prior[srcIdx];
    if (step === 1) return srcIdx === 0 ? 0.48 : prior[srcIdx];
    if (step === 2) return posterior[srcIdx];
    return sampled[srcIdx];
  };

  return (
    <div className="my-6">
      <div className="text-sm font-medium text-slate-400 mb-2 text-center">How GP Updates Flow Between Sources</div>
      <svg viewBox="0 0 500 240" className="w-full bg-slate-900/50 rounded-xl border border-slate-700">
        {/* Reference line at 0.5 */}
        <line x1={50} y1={getY(0.5)} x2={470} y2={getY(0.5)} stroke="#334155" strokeWidth={1} strokeDasharray="4,4" />
        <text x={46} y={getY(0.5) + 4} textAnchor="end" style={{ fontSize: '9px', fill: '#64748b' }}>0.50</text>
        <text x={46} y={getY(0.55) + 4} textAnchor="end" style={{ fontSize: '9px', fill: '#64748b' }}>0.55</text>
        <text x={46} y={getY(0.45) + 4} textAnchor="end" style={{ fontSize: '9px', fill: '#64748b' }}>0.45</text>

        {/* Sources */}
        {sources.map((s, i) => {
          const val = getBarVal(i);
          const y = getY(val);
          const isObserved = step >= 1 && i === 0;
          const isShifted = step >= 2 && i > 0;
          const barColor = step === 3 ? '#10b981' : isObserved ? '#f59e0b' : isShifted ? '#a78bfa' : '#475569';

          return (
            <g key={s.name}>
              {/* Vertical bar */}
              <line x1={s.x + 20} y1={getY(0.5)} x2={s.x + 20} y2={y}
                stroke={barColor} strokeWidth={8} strokeLinecap="round"
                style={{ transition: 'all 0.5s ease-out' }} />
              {/* Value label */}
              <text x={s.x + 20} y={y - 10} textAnchor="middle"
                style={{ fontSize: '11px', fill: barColor, fontWeight: 600, transition: 'all 0.5s ease-out' }}>
                {val.toFixed(3)}
              </text>
              {/* Similarity badge */}
              {step >= 1 && i > 0 && (
                <text x={s.x + 20} y={210} textAnchor="middle"
                  style={{ fontSize: '8px', fill: '#64748b' }}>
                  sim={similarity[i].toFixed(1)}
                </text>
              )}
              {/* Source name */}
              <text x={s.x + 20} y={225} textAnchor="middle"
                style={{ fontSize: '9px', fill: '#94a3b8' }}>
                {s.name}
              </text>
            </g>
          );
        })}

        {/* Connection arrows for step 2+ */}
        {step >= 2 && sources.slice(1).map((s, i) => {
          const opacity = similarity[i + 1] * 0.6;
          return (
            <path key={i} d={`M${sources[0].x + 30},${getY(getBarVal(0))} Q${(sources[0].x + s.x) / 2 + 20},${getY(0.5) - 30} ${s.x + 10},${getY(getBarVal(i + 1))}`}
              fill="none" stroke="#a78bfa" strokeWidth={similarity[i + 1] * 3}
              strokeOpacity={opacity} strokeDasharray="4,2"
              style={{ transition: 'all 0.5s ease-out' }} />
          );
        })}
      </svg>
      {/* Step controls */}
      <div className="flex items-center justify-center gap-2 mt-3">
        {steps.map((s, i) => (
          <button key={i} onClick={() => setStep(i)}
            className={`px-3 py-1.5 text-xs rounded-lg border transition-all ${
              step === i
                ? 'bg-purple-500/30 border-purple-500 text-purple-200'
                : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:border-slate-600'
            }`}>
            <span className="font-medium">{i + 1}.</span> {s.label}
          </button>
        ))}
      </div>
      <div className="text-center text-xs text-slate-500 mt-2">{steps[step].desc}</div>
    </div>
  );
};

// --- Visualization: Kernel Matrix ---
const KernelMatrixViz = () => {
  const sources = ['btc', 'crypto', 'ethtr', 'eth', 'sol', 'begin', 'coinb', 'tax', 'doge', 'memes'];
  const fullNames = ['r/bitcoin', 'r/cryptocurrency', 'r/ethtrader', 'r/ethereum', 'r/solana',
    'r/bitcoinbeginners', 'r/coinbase', 'r/cryptotax', 'r/dogecoin', 'r/cryptocurrencymemes'];
  // Simplified kernel matrix (symmetric, values 0-1)
  const K = [
    [1,.80,.55,.45,.40,.35,.30,.15,.25,.20],
    [.80,1,.50,.50,.42,.38,.32,.18,.22,.18],
    [.55,.50,1,.60,.35,.25,.22,.12,.30,.25],
    [.45,.50,.60,1,.55,.28,.25,.15,.22,.18],
    [.40,.42,.35,.55,1,.22,.20,.12,.18,.15],
    [.35,.38,.25,.28,.22,1,.85,.50,.20,.12],
    [.30,.32,.22,.25,.20,.85,1,.55,.18,.10],
    [.15,.18,.12,.15,.12,.50,.55,1,.10,.05],
    [.25,.22,.30,.22,.18,.20,.18,.10,1,.55],
    [.20,.18,.25,.18,.15,.12,.10,.05,.55,1],
  ];

  const [hovered, setHovered] = useState(null);
  const cellSize = 38;
  const offset = 90;

  const colorScale = (v) => {
    // Purple gradient: 0 = dark slate, 1 = bright purple
    const r = Math.round(30 + v * 137);
    const g = Math.round(41 + v * (99 - 41));
    const b = Math.round(59 + v * (250 - 59));
    return `rgb(${r},${g},${b})`;
  };

  return (
    <div className="my-6">
      <div className="text-sm font-medium text-slate-400 mb-2 text-center">Kernel Correlation Matrix K (source similarity prior)</div>
      <svg viewBox={`0 0 ${offset + cellSize * 10 + 10} ${offset + cellSize * 10 + 10}`}
        className="w-full max-w-lg mx-auto bg-slate-900/50 rounded-xl border border-slate-700">
        {/* Column headers */}
        {sources.map((s, i) => (
          <text key={`col-${i}`} x={offset + i * cellSize + cellSize / 2} y={offset - 8}
            textAnchor="middle" style={{ fontSize: '8px', fill: hovered?.[1] === i ? '#e2e8f0' : '#94a3b8' }}
            transform={`rotate(-45, ${offset + i * cellSize + cellSize / 2}, ${offset - 8})`}>
            {fullNames[i].replace('r/', '')}
          </text>
        ))}
        {/* Row headers */}
        {sources.map((s, i) => (
          <text key={`row-${i}`} x={offset - 5} y={offset + i * cellSize + cellSize / 2 + 3}
            textAnchor="end" style={{ fontSize: '8px', fill: hovered?.[0] === i ? '#e2e8f0' : '#94a3b8' }}>
            {fullNames[i].replace('r/', '')}
          </text>
        ))}
        {/* Cells */}
        {K.map((row, i) => row.map((v, j) => (
          <g key={`${i}-${j}`}
            onMouseEnter={() => setHovered([i, j])}
            onMouseLeave={() => setHovered(null)}>
            <rect x={offset + j * cellSize} y={offset + i * cellSize}
              width={cellSize - 1} height={cellSize - 1} rx={3}
              fill={colorScale(v)}
              stroke={hovered?.[0] === i && hovered?.[1] === j ? '#fff' : 'transparent'}
              strokeWidth={1.5} className="cursor-pointer" />
            {(cellSize > 30 || (hovered?.[0] === i && hovered?.[1] === j)) && (
              <text x={offset + j * cellSize + cellSize / 2 - 0.5}
                y={offset + i * cellSize + cellSize / 2 + 3}
                textAnchor="middle"
                style={{ fontSize: '8px', fill: v > 0.5 ? '#1e1b2e' : '#cbd5e1', fontWeight: v > 0.7 ? 600 : 400 }}>
                {v.toFixed(2)}
              </text>
            )}
          </g>
        )))}
        {/* Tooltip */}
        {hovered && (
          <text x={offset + 5 * cellSize} y={offset + 10 * cellSize + 20} textAnchor="middle"
            style={{ fontSize: '10px', fill: '#e2e8f0' }}>
            {fullNames[hovered[0]]} vs {fullNames[hovered[1]]}: k = {K[hovered[0]][hovered[1]].toFixed(2)}
          </text>
        )}
      </svg>
    </div>
  );
};


// --- Main Blog Post Component ---
const GPBetaBlogPost = () => {
  return (
    <div className="prose prose-invert prose-slate max-w-none
      prose-headings:text-slate-100 prose-headings:font-semibold
      prose-h2:text-2xl prose-h2:mt-8 prose-h2:mb-4
      prose-h3:text-xl prose-h3:mt-6 prose-h3:mb-3
      prose-p:text-slate-300 prose-p:leading-relaxed prose-p:mb-4
      prose-a:text-purple-400 prose-a:no-underline hover:prose-a:text-purple-300
      prose-strong:text-slate-200 prose-strong:font-semibold
      prose-ul:text-slate-300 prose-li:mb-2
      prose-table:border-collapse prose-table:w-full
      prose-th:bg-slate-700/50 prose-th:text-slate-200 prose-th:p-3 prose-th:text-left prose-th:border prose-th:border-slate-600
      prose-td:p-3 prose-td:border prose-td:border-slate-600 prose-td:text-slate-300
      prose-code:text-purple-300 prose-code:bg-slate-700/50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded
      prose-hr:border-slate-700 prose-hr:my-8
      prose-blockquote:border-l-purple-500 prose-blockquote:text-slate-400">

      <h2>The Problem: Every Source Is an Island</h2>
      <p>
        PanicRadar crawls 25+ Reddit communities to measure crypto sentiment. But we can't crawl
        them all at once — we have to choose. So how does the system decide which subreddit to
        check next?
      </p>
      <p>
        It keeps a <strong>scorecard</strong> for every source. Each time we crawl r/bitcoin and its
        sentiment correctly predicted where the price went, we give r/bitcoin a point. Each time it
        got it wrong, we add a mark against it. Mathematically, this scorecard is
        a <strong>Beta distribution</strong> — a simple model defined by two numbers: the count of
        wins (<Eq>{'\\alpha'}</Eq>) and the count of losses (<Eq>{'\\beta'}</Eq>). A source
        with <Eq>{'\\alpha = 60, \\beta = 40'}</Eq> has been right about 60% of the time.
      </p>
      <p>
        To decide which source to crawl next, the system uses <strong>Thompson Sampling</strong> — a
        strategy for balancing exploration and exploitation. Instead of always picking the source
        with the best track record (which would mean ignoring newer sources), it rolls a random
        number <em>from each source's scorecard</em>. Sources with better track records tend to
        roll higher, but there's always a chance that an underdog rolls high too. This lets the
        system keep exploring without wasting too many crawls on proven losers.
      </p>
      <p>
        Here's the problem: <strong>every source is an island</strong>. When we observe that r/bitcoin
        gave us a good signal, we update its scorecard. But r/cryptocurrency, which covers similar
        topics with overlapping users, learns <em>nothing</em> from that observation. It has to discover
        its own accuracy from scratch. Same for r/bitcoinmarkets, r/ethtrader, and every other
        related community.
      </p>
      <p>
        With 25 correlated sources, this is wasteful. A human would naturally think: "if r/bitcoin
        is accurate, r/cryptocurrency probably is too — they discuss the same market." We wanted
        our system to reason the same way. Instead of 25 isolated islands, we wanted a connected
        archipelago where knowledge flows between similar communities.
      </p>

      <h2>The Idea: Connecting the Islands</h2>
      <p>
        The fix is to model all sources <em>jointly</em> instead of independently. The key insight:
        sources that look similar — similar sentiment patterns, similar volatility, similar fear
        levels — should share statistical strength. When one island gets new data, nearby islands
        should feel the ripples.
      </p>
      <p>
        We use a <strong>Gaussian Process (GP)</strong> to model this connection structure. Think of
        it as an underwater cable network linking the islands. The GP measures how similar each pair
        of sources is and uses that to propagate belief updates across the network.
      </p>
      <p>The resulting system has three layers:</p>
      <ul>
        <li><strong>Beta scorecards</strong> — each source still tracks its own wins and losses (fast, exact, battle-tested)</li>
        <li><strong>Gaussian Process</strong> — models which sources are connected and how strongly, based on their behavior</li>
        <li><strong>Correlated Thompson Sampling</strong> — when rolling the dice, similar sources get correlated rolls instead of independent ones</li>
      </ul>
      <p>We call it the <strong>GP-Beta hybrid</strong>.</p>

      <h2>Step 1: Describing Each Source With Features</h2>
      <p>
        To know which sources are "similar," we need to describe them numerically. We extract
        a <strong>7-dimensional feature vector</strong> from each source's recent sentiment data (last 7 days):
      </p>
      <table>
        <thead>
          <tr><th>Feature</th><th>What It Measures</th></tr>
        </thead>
        <tbody>
          <tr><td>Mean sentiment score</td><td>Central tendency — is this source bullish or bearish?</td></tr>
          <tr><td>Sentiment volatility</td><td>Standard deviation — does it swing wildly or stay steady?</td></tr>
          <tr><td>Mean fear index</td><td>How much panic/loss content appears</td></tr>
          <tr><td>Mean euphoria index</td><td>How much moon/FOMO content appears</td></tr>
          <tr><td>Mean activity level</td><td>Prevalence of scam warnings and market chatter</td></tr>
          <tr><td>Polarity ratio</td><td>Proportion of positive vs negative posts</td></tr>
          <tr><td>Log post volume</td><td>How active the community is (log-scaled)</td></tr>
        </tbody>
      </table>
      <p>
        All features are <strong>z-scored</strong> (subtract mean, divide by standard deviation) so
        no single dimension dominates. After this, each source is a point in 7D space, and we can
        measure distances between them.
      </p>

      <SourceFeatureViz />

      <p>
        For example, r/bitcoinbeginners and r/coinbase end up very close (distance 1.10) — both
        have moderate sentiment, low volatility, and similar activity levels. Meanwhile
        r/cryptocurrencymemes is far from r/cryptotax (distance 5.24) — completely different communities.
      </p>

      <h2>Step 2: The Kernel — Measuring Source Similarity</h2>
      <p>
        The GP uses a <strong>kernel function</strong> to quantify how similar two sources are.
        We use a composite kernel with three components:
      </p>

      <h3>RBF (Radial Basis Function)</h3>
      <p>The main similarity measure. Two sources with similar feature vectors get a high kernel value:</p>
      <Eq display>{`k_{\\text{rbf}}(\\mathbf{x}_i, \\mathbf{x}_j) = \\sigma_f^2 \\cdot \\exp\\!\\left(-\\frac{\\|\\mathbf{x}_i - \\mathbf{x}_j\\|^2}{2\\ell^2}\\right)`}</Eq>
      <p>
        Where <Eq>{'\\|\\mathbf{x}_i - \\mathbf{x}_j\\|'}</Eq> is the Euclidean distance between feature
        vectors, <Eq>{'\\ell'}</Eq> is the length scale (how far "similar" extends),
        and <Eq>{'\\sigma_f^2'}</Eq> is the signal variance.
      </p>

      <h3>Categorical Bonus</h3>
      <p>Sources of the same type (e.g., both Reddit subs) get an extra similarity bump:</p>
      <Eq display>{`k_{\\text{cat}}(\\mathbf{x}_i, \\mathbf{x}_j) = \\sigma_{\\text{cat}}^2 \\cdot \\delta(\\text{type}_i, \\text{type}_j)`}</Eq>
      <p>
        Where <Eq>{'\\delta'}</Eq> is 1 if the types match, 0 otherwise.
      </p>

      <h3>Noise Term</h3>
      <p>Each source has some irreducible observation noise:</p>
      <Eq display>{`k_{\\text{noise}}(\\mathbf{x}_i, \\mathbf{x}_j) = \\sigma_n^2 \\cdot \\mathbb{I}(i = j)`}</Eq>

      <p>The full composite kernel is their sum:</p>
      <Eq display>{`k(\\mathbf{x}_i, \\mathbf{x}_j) = k_{\\text{rbf}} + k_{\\text{cat}} + k_{\\text{noise}}`}</Eq>
      <p>
        This gives us a <strong>kernel matrix</strong> <Eq>{'\\mathbf{K}'}</Eq> where entry <Eq>{'(i,j)'}</Eq> tells
        us how correlated sources <Eq>{'i'}</Eq> and <Eq>{'j'}</Eq> should be.
        Four hyperparameters control the kernel: <Eq>{'\\ell'}</Eq>, <Eq>{'\\sigma_f^2'}</Eq>, <Eq>{'\\sigma_{\\text{cat}}^2'}</Eq>,
        and <Eq>{'\\sigma_n^2'}</Eq>.
      </p>

      <KernelMatrixViz />

      <h2>Step 3: Moment Matching — Connecting Beta to GP</h2>
      <p>
        Here's the tricky part. Each source has a <Eq>{'\\text{Beta}(\\alpha, \\beta)'}</Eq> distribution
        (discrete binary observations), but the GP works in <strong>Gaussian</strong> (continuous normal)
        space. We need a bridge.
      </p>
      <p>
        We use the <strong>probit link function</strong> — the inverse of the standard normal
        CDF, <Eq>{'\\Phi^{-1}'}</Eq>. This maps probabilities in [0, 1] to the entire real line.
      </p>

      <h3>Convert the Beta mean to Gaussian space</h3>
      <Eq display>{`\\mu_{\\text{obs}} = \\Phi^{-1}\\!\\left(\\frac{\\alpha}{\\alpha + \\beta}\\right)`}</Eq>
      <p>
        For example, a source with 60% accuracy (<Eq>{'\\alpha=60, \\beta=40'}</Eq>) maps
        to <Eq>{'\\Phi^{-1}(0.6) = 0.253'}</Eq> in probit space.
      </p>

      <h3>Convert the Beta variance using the delta method</h3>
      <Eq display>{`\\sigma^2_{\\text{obs}} = \\frac{1}{\\phi(\\mu)^2 \\cdot (\\alpha + \\beta + 1)}`}</Eq>
      <p>
        Where <Eq>{'\\phi'}</Eq> (lowercase) is the standard normal PDF. Sources with more
        observations (larger <Eq>{'\\alpha + \\beta'}</Eq>) have smaller variance — we're more certain about them.
      </p>

      <ProbitTransformViz />

      <h2>Step 4: The GP Posterior — Where the Magic Happens</h2>
      <p>Now we have:</p>
      <ul>
        <li>A kernel matrix <Eq>{'\\mathbf{K}'}</Eq> encoding source similarity</li>
        <li>Gaussian observations <Eq>{'\\boldsymbol{\\mu}_{\\text{obs}}'}</Eq> with
          variances <Eq>{'\\sigma^2_{\\text{obs}}'}</Eq> for each source</li>
      </ul>
      <p>
        The GP posterior combines these using Bayes' rule.
        Let <Eq>{'\\boldsymbol{\\Lambda} = \\text{diag}(1/\\sigma^2_1, \\ldots, 1/\\sigma^2_n)'}</Eq> be
        the precision matrix (inverse variances).
      </p>

      <p><strong>Posterior covariance:</strong></p>
      <Eq display>{`\\boldsymbol{\\Sigma}_{\\text{post}} = \\left(\\mathbf{K}^{-1} + \\boldsymbol{\\Lambda}\\right)^{-1}`}</Eq>

      <p><strong>Posterior mean:</strong></p>
      <Eq display>{`\\boldsymbol{\\mu}_{\\text{post}} = \\boldsymbol{\\Sigma}_{\\text{post}} \\cdot \\boldsymbol{\\Lambda} \\cdot \\boldsymbol{\\mu}_{\\text{obs}}`}</Eq>

      <p>This is the key equation. Look at what it does:</p>
      <ul>
        <li><Eq>{'\\mathbf{K}^{-1}'}</Eq> is the <strong>prior precision</strong> — how much the kernel structure constrains things</li>
        <li><Eq>{'\\boldsymbol{\\Lambda}'}</Eq> is the <strong>observation precision</strong> — how much we trust each source's data</li>
        <li>The posterior balances these two forces</li>
      </ul>
      <p>
        When a source has lots of observations (large <Eq>{'\\alpha + \\beta'}</Eq>),
        its <Eq>{'\\boldsymbol{\\Lambda}'}</Eq> entry is large, so the posterior stays close to its observed
        value. But when a source has few observations, the kernel pulls it toward similar
        sources. <strong>Knowledge flows from data-rich sources to data-poor ones.</strong>
      </p>

      <GPUpdateFlowViz />

      <h2>Step 5: Correlated Thompson Sampling</h2>
      <p>Standard Thompson Sampling draws <em>independently</em> from each source's Beta distribution:</p>
      <Eq display>{`\\theta_i \\sim \\text{Beta}(\\alpha_i, \\beta_i) \\quad \\text{for each source independently}`}</Eq>
      <p>This ignores correlations entirely. Our GP-Beta hybrid draws <em>jointly</em>:</p>

      <p><strong>Draw a sample from the GP posterior:</strong></p>
      <Eq display>{`\\mathbf{z} \\sim \\mathcal{N}(\\boldsymbol{\\mu}_{\\text{post}},\\; \\boldsymbol{\\Sigma}_{\\text{post}})`}</Eq>
      <p>
        This is a single draw from a multivariate normal — all sources are sampled simultaneously,
        with correlations encoded in <Eq>{'\\boldsymbol{\\Sigma}_{\\text{post}}'}</Eq>.
      </p>

      <p><strong>Map back to probabilities:</strong></p>
      <Eq display>{`\\theta_i = \\Phi(z_i)`}</Eq>
      <p>
        The probit function <Eq>{'\\Phi'}</Eq> maps each sample back to [0, 1].
        The result: <strong>correlated probability samples</strong>.
      </p>

      <SamplingComparisonViz />

      <p>
        When <Eq>{'z_i'}</Eq> is high for r/bitcoin, <Eq>{'z_j'}</Eq> tends to be high for
        r/cryptocurrency too (because <Eq>{'\\boldsymbol{\\Sigma}_{\\text{post}}'}</Eq> has positive
        off-diagonal entries for similar sources). The bandit naturally groups similar sources
        together in its exploration.
      </p>

      <h2>Step 6: Hyperparameter Optimization</h2>
      <p>
        The four kernel hyperparameters control how much information flows between sources.
        We optimize them by maximizing the <strong>marginal log-likelihood</strong>:
      </p>
      <Eq display>{`\\log p(\\mathbf{y} \\mid \\mathbf{X}, \\boldsymbol{\\theta}) = -\\frac{1}{2}\\left[\\mathbf{y}^\\top (\\mathbf{K} + \\boldsymbol{\\Lambda}^{-1})^{-1} \\mathbf{y} + \\log|\\mathbf{K} + \\boldsymbol{\\Lambda}^{-1}| + n\\log 2\\pi\\right]`}</Eq>
      <p>
        Where <Eq>{'\\mathbf{y} = \\boldsymbol{\\mu}_{\\text{obs}}'}</Eq> and <Eq>{'\\mathbf{X}'}</Eq> are
        the source features. This balances model fit against complexity — it prefers the simplest
        kernel that explains the observed data well.
      </p>
      <p>
        We use <strong>L-BFGS-B</strong> (a quasi-Newton optimizer) with bounded constraints.
        With only 30 sources and 4 parameters, this takes milliseconds. The optimization runs
        every 50 belief evaluations, so the kernel adapts as the system collects more data.
      </p>

      <h2>The Three-Tier Fallback</h2>
      <p>Not every source can participate in the GP. We use a tiered system:</p>
      <ol className="list-decimal list-inside space-y-2 text-slate-300">
        <li><strong>GP-eligible</strong> (10+ crawls AND features available): correlated Thompson Sampling via the GP posterior</li>
        <li><strong>Cold-start</strong> (fewer than 10 crawls or no features): independent Beta sampling</li>
        <li><strong>System fallback</strong> (fewer than 5 GP-eligible sources or numerical issues): full fallback to independent Thompson Sampling</li>
      </ol>
      <p>
        The GP is purely additive — it can only help, never hurt. If anything goes wrong, we
        gracefully degrade to the battle-tested independent approach.
      </p>

      <h2>What We Observed</h2>
      <p>After fitting the GP to our live data (13 active sources), some patterns emerged:</p>
      <p><strong>Most similar pairs:</strong></p>
      <ul>
        <li>r/bitcoinbeginners and r/coinbase (distance: 1.10) — both serve newcomers</li>
        <li>r/bitcoin and r/cryptocurrency (distance: 1.56) — the two main hubs</li>
        <li>r/cryptocurrencymemes and r/cryptomarkets (distance: 1.88) — both low-activity</li>
      </ul>
      <p><strong>Least similar:</strong></p>
      <ul>
        <li>r/cryptotax and r/cryptocurrencymemes (distance: 5.24) — tax advice vs memes</li>
        <li>r/cryptotax and r/dogecoin (distance: 4.81) — completely different cultures</li>
      </ul>
      <p>
        These groupings match intuition, which gives us confidence the feature vectors capture
        meaningful source characteristics.
      </p>

      <h2>Why Not a Simpler Approach?</h2>
      <p><strong>Why not just cluster sources?</strong></p>
      <p>
        Clustering forces hard boundaries — a source is either in the cluster or not. The GP
        gives soft, continuous similarity. r/ethereum might be 70% similar to r/bitcoin and 30%
        similar to r/defi, and the GP handles this naturally.
      </p>
      <p><strong>Why not a pure GP classification model?</strong></p>
      <p>
        A pure GP classifier over all 7000+ historical observations would need enormous matrices.
        The Beta sufficient statistics compress all history into just two numbers per
        source (<Eq>{'\\alpha, \\beta'}</Eq>). The hybrid gets the best of both.
      </p>
      <p><strong>Why not just a correlation matrix?</strong></p>
      <p>
        A sample correlation matrix would be noisy with only 30 sources. The GP kernel imposes
        smoothness via the RBF function, giving us a principled correlation structure even with
        limited data. Plus, the kernel can extrapolate to new sources based on their features.
      </p>

      <h2>Summary</h2>
      <p>The GP-Beta hybrid lets our crawler share knowledge between similar sources:</p>
      <ol className="list-decimal list-inside space-y-2 text-slate-300">
        <li><strong>Feature vectors</strong> (7D) describe each source's sentiment behavior</li>
        <li><strong>Composite kernel</strong> measures similarity in feature space</li>
        <li><strong>Moment matching</strong> bridges Beta and Gaussian distributions via the probit link</li>
        <li><strong>GP posterior</strong> fuses the kernel prior with observed data</li>
        <li><strong>Correlated Thompson Sampling</strong> draws joint probability samples</li>
        <li><strong>Hyperparameter optimization</strong> tunes the kernel automatically</li>
      </ol>
      <p>
        The result: when one source proves accurate, similar sources benefit. The crawler learns
        faster, explores more efficiently, and makes better decisions about where to crawl next.
      </p>
      <p>
        You can see the source similarity visualization on our <a href="/beliefs">Beliefs dashboard</a> —
        including the heatmap showing which sources behave most alike.
      </p>

      <hr />
      <p className="text-slate-500 text-sm italic">
        All the math in this post is implemented in our open-source codebase.
        See <a href="https://github.com/protostatis/panicradar">gp_model.py</a> for
        the GP implementation and <a href="https://github.com/protostatis/panicradar">feature_extraction.py</a> for
        the feature pipeline.
      </p>
    </div>
  );
};

export default GPBetaBlogPost;
