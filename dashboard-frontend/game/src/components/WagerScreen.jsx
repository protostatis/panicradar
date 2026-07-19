/**
 * WagerScreen — V2 street-based wagering match (PvA-first slice).
 *
 * Renders the match-3 board (reusing Board), a wager HUD (pot / street /
 * committed demo coins / bet controls), the standings, and the game-over
 * overlay. All wagering logic is driven by useWagerController + game/wagering.js.
 * Demo coins only; no real money; fold always available.
 */
import React, { useEffect } from 'react';
import Board from './Board';
import GameOverOverlay from './GameOverOverlay';
import { useWagerController } from '../game/useWagerController';
import { BET_ACTION, WAGER_PHASE } from '../game/wagering';

function phaseLabel(phase, street, moveKind) {
  if (phase === WAGER_PHASE.ANTE) return 'Posting ante…';
  if (phase === WAGER_PHASE.STREET_MOVE && moveKind === 'river_bonus') return 'Final bonus swap — one move each, then showdown';
  if (phase === WAGER_PHASE.STREET_MOVE) return `Street: ${street || '—'} — make your swap`;
  if (phase === WAGER_PHASE.BETTING) return `Street: ${street || '—'} — betting round`;
  if (phase === WAGER_PHASE.SHOWDOWN) return 'Showdown…';
  if (phase === WAGER_PHASE.COMPLETE) return 'Hand complete';
  return '';
}

export default function WagerScreen({ playerName, agentKey, agentModel, agentName, onMenu }) {
  const c = useWagerController({ agentKey, agentModel, agentName });

  useEffect(() => {
    c.start(playerName);
    return () => c.reset();
  }, []); // eslint-disable-line

  const w = c.wager;
  const betting = c.wagerPhase === WAGER_PHASE.BETTING;
  const agentActing = c.agentActing;

  const you = c.humanSeat;
  const agent = c.agentSeat;
  const toCall = betting ? Math.max(0, c.currentBet - (you?.committed || 0)) : 0;
  const canCheck = betting && toCall === 0;
  const facing = betting && toCall > 0;
  const canAffordCall = !!you && you.coins >= toCall;
  const canAffordRaise = !!you && you.coins >= toCall + c.raiseAmount;

  return (
    <div className="game-screen wager-screen">
      {/* One integrated match HUD — street / pot / to-call / phase + both
          players' coins, match points and pot commitment, in a single panel. */}
      <div className="match-hud">
        <div className="match-hud-row match-hud-stats">
          <div className="hud-chip">
            <span className="hud-label">Street</span>
            <span className="hud-value">{w ? (w.street || 'ante') : '—'}</span>
          </div>
          <div className="hud-chip hud-chip--pot">
            <span className="hud-label">Pot</span>
            <span className="hud-value">{c.pot} cr</span>
          </div>
          <div className="hud-chip">
            <span className="hud-label">To call</span>
            <span className="hud-value">{toCall} cr</span>
          </div>
          <div className="hud-chip">
            <span className="hud-label">Phase</span>
            <span className="hud-value hud-value--phase">{phaseLabel(c.wagerPhase, c.street, c.moveKind)}</span>
          </div>
          {c.countdown > 0 && c.canBet && (
            <div className="hud-chip hud-chip--timer">
              <span className="hud-label">Time</span>
              <span className={`hud-value${c.countdown <= 10 ? ' hud-value--urgent' : ''}`}>{c.countdown}s</span>
            </div>
          )}
        </div>

        <div className="match-hud-row match-hud-players">
          <div className={`player-chip player-chip--you${you && you.committed > 0 ? ' player-chip--in' : ''}${c.wagerPhase === WAGER_PHASE.BETTING && c.canBet ? ' player-chip--active' : ''}`}>
            <span className="player-name">{you ? you.name : 'You'}</span>
            <span className="player-coins">{you ? you.coins : 0} cr</span>
            <span className="player-pts">{you ? (you.score || 0) : 0} pts</span>
            {you && you.committed > 0 && <span className="player-committed">in pot {you.committed}</span>}
          </div>

          <div className="player-vs">VS</div>

          <div className={`player-chip player-chip--agent${agent && agent.committed > 0 ? ' player-chip--in' : ''}${agentActing ? ' player-chip--active' : ''}`}>
            <span className="player-name">{agent ? agent.name : 'AI Agent'} 🤖</span>
            <span className="player-coins">{agent ? agent.coins : 0} cr</span>
            <span className="player-pts">{agent ? (agent.score || 0) : 0} pts</span>
            {agent && agent.committed > 0 && <span className="player-committed">in pot {agent.committed}</span>}
          </div>
        </div>

        <StatusBarBridge wager={w} thinking={c.thinking} agentActing={agentActing} message={c.message} />
      </div>

      <div className={`board-wrap${agentActing ? ' board-wrap--agent' : ''}`}>
        <Board cells={c.cells} selected={c.selected} matchedIndices={c.matchedIndices} hintIndices={c.hintIndices} interactive={c.wagerPhase === WAGER_PHASE.STREET_MOVE && !agentActing} onPick={c.handleClick} />
        {agentActing && (
          <div className="agent-turn-overlay">
            <div className="agent-turn-card">
              <div className="agent-avatar">🤖</div>
              <div className="agent-turn-text">
                <strong>{c.thinking ? `${agentName || 'AI Agent'} is thinking…` : `${agentName || 'AI Agent'} is making a move…`}</strong>
                <span className="agent-turn-sub">{c.thinking ? 'Querying the model' : 'Resolving swap & cascades'}</span>
              </div>
              <div className="agent-spinner" />
            </div>
          </div>
        )}
      </div>

      <p className="wager-disclaimer">Demo coins only · no real money · game of skill · fold anytime</p>

      {w && w.settled && (
        <div className="wager-log">
          <h4>Hand log</h4>
          <ul>{c.lastLog.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </div>
      )}

      {/* Bet prompt as a pop-up — only when it is YOUR turn to bet and the hand
          is still live (never after the winner is decided). The session-finished
          guard keeps it from ever appearing over the game-over overlay. */}
      {c.canBet && !(w && w.settled) && c.session?.status !== 'finished' && (
        <div className="bet-modal-overlay">
          <div className="bet-modal" role="dialog" aria-modal="true" aria-labelledby="bet-modal-title">
            <div className="bet-modal-head">
              <strong id="bet-modal-title">Your turn to bet</strong>
              <span className="bet-modal-sub">
                {facing
                  ? `${agent ? agent.name : 'Agent'} raised — you must Call ${toCall} cr or Fold`
                  : 'No bet to face — you may Check or open with a Raise'}
              </span>
            </div>
            <div className="bet-modal-actions">
              <button className="btn" onClick={() => c.humanBet(BET_ACTION.CHECK)} disabled={!canCheck && facing}>
                {canCheck ? 'Check' : 'Check (free)'}
              </button>
              <button className="btn btn-primary" onClick={() => c.humanBet(BET_ACTION.CALL)} disabled={!facing || !canAffordCall}>
                {facing && !canAffordCall ? `Can't call ${toCall} cr` : `Call ${toCall} cr`}
              </button>
              <button className="btn" onClick={() => c.humanBet(BET_ACTION.RAISE, c.raiseAmount)} disabled={!w || w.raiseCountThisStreet >= 1 || !canAffordRaise}>
                Raise {c.raiseAmount} cr
              </button>
              <button className="btn btn-danger" onClick={() => c.humanBet(BET_ACTION.FOLD)}>
                Fold
              </button>
            </div>
          </div>
        </div>
      )}

      <GameOverOverlay session={c.session} onPlayAgain={() => c.start(playerName)} onMenu={onMenu} />

      <button className="btn btn-menu" onClick={onMenu}>Menu</button>
    </div>
  );
}

// Lightweight status bar that shows whose turn / phase without depending on the
// old move-limit session shape.
function StatusBarBridge({ wager, thinking, agentActing, message }) {
  if (!wager) return null;
  const actor = wager.phase === WAGER_PHASE.BETTING
    ? wager.seats.find((s) => !s.folded && !s.actedThisStreet)
    : null;
  const turnLabel = agentActing
    ? `${thinking ? '🤖 thinking' : '🤖 acting'}`
    : actor ? actor.name : '—';
  return (
    <div className={`status-bar${agentActing ? ' status-bar--agent' : ''}`}>
      <div className="stat">
        <span className="stat-label">Turn</span>
        <span className="stat-value">{turnLabel}</span>
      </div>
      <div className="stat stat-msg">
        <span className="stat-value" style={{ fontSize: '0.95rem' }}>{message || ''}</span>
      </div>
    </div>
  );
}
