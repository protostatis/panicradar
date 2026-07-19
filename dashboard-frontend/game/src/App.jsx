import { useEffect, useState } from 'react';
import './App.css';
import WagerScreen from './components/WagerScreen';
import { trackGameEvent, trackGamePageView } from './utils/analytics';

export default function App() {
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    trackGamePageView();
  }, []);

  const startGame = () => {
    trackGameEvent('game_start', { game_name: 'blockcoined' });
    setPlaying(true);
  };

  if (playing) {
    return (
      <div className="app">
        <a href="/" className="back-link" style={{ alignSelf: 'flex-start', color: '#8b949e', fontSize: '0.82rem', textDecoration: 'none', marginBottom: 4 }}>
          &larr; Back to PanicRadar.ai
        </a>
        <WagerScreen
          playerName=""
          agentKey=""
          agentModel=""
          agentName=""
          onMenu={() => setPlaying(false)}
        />
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">BlockCoined</h1>
        <p className="app-subtitle">A match-3 game of skill &mdash; you vs the AI</p>
      </header>
      <div className="v2-card">
        <h2 className="v2-card-title">Wagered vs AI</h2>
        <p className="v2-card-desc">
          Swap coins to line up 3+ matches and out-score the AI across three
          streets &mdash; flop, turn, river &mdash; then bet, raise, or fold for demo
          coins. Demo coins only &middot; no real money.
        </p>
        <button className="btn btn-v2" onClick={startGame}>
          V2 &mdash; Wagered vs AI (demo)
        </button>
      </div>
      <a href="/" style={{ marginTop: 26, display: 'block', textAlign: 'center', color: '#8b949e', fontSize: '0.85rem', textDecoration: 'none' }}>
        &larr; Back to PanicRadar.ai
      </a>
    </div>
  );
}
