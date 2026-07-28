import React, { useEffect, useState } from 'react';
import './App.css';
import WagerScreen from './components/WagerScreen';
import V2PvpLobby from './components/V2PvpLobby';
import V2PvpScreen from './components/V2PvpScreen';
import TutorialScreen from './components/TutorialScreen';
import { V2PvpTransport } from './transports/v2PvpTransport';
import { clearSession } from './utils/storage';
import { trackGameEvent, trackGamePageView } from './utils/analytics';

export default function App() {
  const [playing, setPlaying] = useState(false);
  const [showTutorial, setShowTutorial] = useState(false);
  const [showPvP, setShowPvP] = useState(false);
  const [v2PvpSession, setV2PvpSession] = useState(null);
  const [v2PvpMatch, setV2PvpMatch] = useState(null);
  const [v2PvpConnectionError, setV2PvpConnectionError] = useState('');
  const [v2PvpConnectAttempt, setV2PvpConnectAttempt] = useState(0);

  useEffect(() => {
    trackGamePageView();
  }, []);

  const startGame = () => {
    trackGameEvent('game_start', { game_name: 'blockcoined' });
    setPlaying(true);
  };

  // ---- V2 PvP connection ----

  useEffect(() => {
    if (!showPvP) return undefined;
    if (v2PvpSession) return undefined;

    const transport = new V2PvpTransport();
    let handedOff = false;
    let cancelled = false;

    transport.connect()
      .then((identity) => {
        if (cancelled) {
          transport.close();
          return;
        }
        handedOff = true;
        setV2PvpSession({ transport, identity });
        setV2PvpConnectionError('');
      })
      .catch((error) => {
        if (!cancelled) {
          transport.close();
          setV2PvpConnectionError(error.message || 'Unable to connect to the match lobby');
        }
      });

    return () => {
      cancelled = true;
      if (!handedOff) transport.close();
    };
  }, [showPvP, v2PvpSession, v2PvpConnectAttempt]);

  useEffect(() => {
    const transport = v2PvpSession?.transport;
    if (!transport) return undefined;

    return transport.onMessage((msg) => {
      if (msg.type === 'IDENTITY_OK') {
        setV2PvpSession((current) => (
          current?.transport === transport ? { ...current, identity: msg.self } : current
        ));
      } else if (msg.type === 'MATCH_STARTED') {
        setV2PvpMatch({ transport });
      } else if (msg.type === 'MATCH_ENDED') {
        setV2PvpMatch(null);
      }
    });
  }, [v2PvpSession?.transport]);

  const returnToV2Lobby = () => {
    v2PvpSession?.transport.leaveMatch();
    setV2PvpMatch(null);
  };

  const backToMenu = () => {
    const v2Transport = v2PvpSession?.transport || v2PvpMatch?.transport;
    if (v2Transport) {
      v2Transport.leaveMatch();
      v2Transport.close();
    }
    setPlaying(false);
    setShowTutorial(false);
    setShowPvP(false);
    setV2PvpSession(null);
    setV2PvpMatch(null);
    setV2PvpConnectionError('');
  };

  const handleNewIdentity = () => {
    // Tear down the existing connection
    const v2Transport = v2PvpSession?.transport || v2PvpMatch?.transport;
    if (v2Transport) {
      v2Transport.leaveMatch();
      v2Transport.close();
    }
    // Clear the persisted session so the next connect creates a fresh identity
    clearSession();
    // Reset all PvP state and trigger a new connection
    setV2PvpSession(null);
    setV2PvpMatch(null);
    setV2PvpConnectionError('');
    setV2PvpConnectAttempt((attempt) => attempt + 1);
  };

  // ---- PvP screen ----
  if (showPvP) {
    return (
      <div className="app">
        {v2PvpMatch ? (
          <V2PvpScreen
            transport={v2PvpMatch.transport}
            myId={v2PvpSession?.identity?.userId}
            onLobby={returnToV2Lobby}
          />
        ) : (
          <>
            <a href="/" className="back-link" style={{ alignSelf: 'flex-start', color: '#8b949e', fontSize: '0.82rem', textDecoration: 'none', marginBottom: 4 }}>
              &larr; Back to PanicRadar.ai
            </a>
            <header className="app-header"><h1 className="app-title">BlockCoined</h1></header>
            <V2PvpLobby
              session={v2PvpSession}
              connectionError={v2PvpConnectionError}
              onRetry={() => {
                setV2PvpConnectionError('');
                setV2PvpConnectAttempt((attempt) => attempt + 1);
              }}
              onNewIdentity={handleNewIdentity}
            />
            <button className="btn btn-menu" onClick={backToMenu}>Menu</button>
          </>
        )}
      </div>
    );
  }

  // ---- Tutorial ----
  if (showTutorial) {
    return (
      <div className="app">
        <TutorialScreen
          onDone={() => { setShowTutorial(false); setPlaying(true); }}
          onSkip={() => { setShowTutorial(false); setPlaying(true); }}
        />
        <button className="btn btn-menu" onClick={backToMenu}>← Menu</button>
      </div>
    );
  }

  // ---- PvA game ----
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

  // ---- Landing menu ----
  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">BlockCoined</h1>
        <p className="app-subtitle">A multiplayer match-3 game of skill — play vs AI or challenge a friend</p>
      </header>
      <div className="v2-card v2-card--tutorial">
        <h2 className="v2-card-title">✨ Try the Game</h2>
        <p className="v2-card-desc">
          New to BlockCoined? Step through a quick interactive tutorial &mdash; learn
          how to swap, match, and chain in under a minute. No opponent, no timer,
          no coins at stake.
        </p>
        <button className="btn btn-tutorial" onClick={() => setShowTutorial(true)}>
          Start Tutorial
        </button>
      </div>
      <div className="v2-card">
        <h2 className="v2-card-title">Wagered vs AI</h2>
        <p className="v2-card-desc">
          Swap coins to line up 3+ matches and out-score the AI across three
          streets &mdash; flop, turn, river &mdash; then bet, raise, or fold for demo
          coins. Demo coins only &middot; no real money.
        </p>
        <button className="btn btn-v2" onClick={startGame}>
          Play vs AI
        </button>
      </div>
      <div className="v2-card" style={{ marginTop: 18 }}>
        <h2 className="v2-card-title">Play with a friend</h2>
        <p className="v2-card-desc">
          Challenge another player in a live match over demo credits. Both
          players connect to the lobby, challenge, and play by the same V2
          wagering rules. Your guest identity persists across page reloads.
        </p>
        <p className="v2-card-desc" style={{ color: '#f4d03f', fontSize: '0.78rem', marginTop: 4 }}>
          Demo balances reset on server restart. Demo credits only — no real money.
        </p>
        <button className="btn btn-v2" style={{ background: 'linear-gradient(135deg, #4facfe, #00f2fe)' }} onClick={() => {
          trackGameEvent('game_start', { game_name: 'blockcoined_pvp' });
          setShowPvP(true);
        }}>
          Play with a friend
        </button>
      </div>
      <a href="/" style={{ marginTop: 26, display: 'block', textAlign: 'center', color: '#8b949e', fontSize: '0.85rem', textDecoration: 'none' }}>
        &larr; Back to PanicRadar.ai
      </a>
    </div>
  );
}
