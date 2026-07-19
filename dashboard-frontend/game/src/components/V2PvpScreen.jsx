/**
 * V2PvpScreen — networked V2 wagered PvP screen.
 *
 * Renders the match-3 board (reusing Board), a wager HUD (pot,
 * street, phase, both player chips with coins/points, deadline countdown),
 * a bottom bet-modal when it's the user's turn to bet, and a game-over
 * overlay when the hand is complete.
 *
 * All game logic is server-authoritative; this component only displays
 * snapshots and forwards user intent through usePvpWagerController.
 */
import React from 'react';
import Board from './Board';
import { usePvpWagerController } from '../game/usePvpWagerController';
import { WAGER_PHASE, BET_ACTION } from '../game/wagering';

/** Human-readable phase/stage label. */
function phaseLabel(phase, moveKind) {
  if (phase === WAGER_PHASE.ANTE) return 'Posting ante…';
  if (phase === WAGER_PHASE.STREET_MOVE && moveKind === 'river_bonus')
    return 'Final bonus swap — one move each, then showdown';
  if (phase === WAGER_PHASE.STREET_MOVE) return 'Make your swap';
  if (phase === WAGER_PHASE.BETTING) return 'Betting round';
  if (phase === WAGER_PHASE.SHOWDOWN) return 'Showdown…';
  if (phase === WAGER_PHASE.COMPLETE) return 'Hand complete';
  return '';
}

/** Small local game-over overlay — avoids the data-shape mismatch of GameOverOverlay. */
function WinnerOverlay({
  session,
  onLobby,
  onRematch,
  rematchRequestedByMe,
  opponentRequestedRematch,
}) {
  if (!session || session.status !== 'finished') return null;

  const rows = session.players;
  const winners = rows.filter((r) => session.winnerIds.includes(r.id));
  const title =
    winners.length === 0
      ? 'Draw!'
      : winners.length === 1
        ? `${winners[0].name} wins!`
        : `Draw — tied: ${winners.map((w) => w.name).join(', ')}`;

  return (
    <div className="game-over-overlay">
      <div className="game-over-box">
        <h1>{title}</h1>
        <ul className="final-standings">
          {rows.map((r, i) => (
            <li key={r.id}>
              <span>
                {i + 1}. {r.name}
              </span>
              <strong>{r.score} pts</strong>
            </li>
          ))}
        </ul>
        {session.pool > 0 && winners.length === 1 && (
          <p className="game-over-turns">
            {winners[0].name} takes the {session.pool} credit pot
          </p>
        )}
        <p className="rematch-status">
          {rematchRequestedByMe
            ? 'Rematch request sent. Waiting for your opponent to agree.'
            : opponentRequestedRematch
              ? 'Your opponent wants a rematch.'
              : 'Both players must agree before a new match begins.'}
        </p>
        <div className="game-over-actions">
          <button
            className="btn btn-primary btn-large"
            disabled={rematchRequestedByMe}
            onClick={onRematch}
          >
            {rematchRequestedByMe
              ? 'Waiting for opponent…'
              : opponentRequestedRematch
                ? 'Accept rematch'
                : 'Request rematch'}
          </button>
          <button className="btn btn-large" onClick={onLobby}>
            Find another match
          </button>
        </div>
      </div>
    </div>
  );
}

export default function V2PvpScreen({ transport, myId, onLobby }) {
  const c = usePvpWagerController({ transport, myId });

  const w = c.wager;
  const isLobby = c.lifecycle === 'lobby';
  const isActive = c.lifecycle === 'active';
  const isSwapTurn = c.wagerPhase === WAGER_PHASE.STREET_MOVE;
  const waitingForSwap = isActive && isSwapTurn && !c.isMyMove && !c.isAnimating;

  return (
    <div className="game-screen">
      {/* ---- Top bar ---- */}
      <div className="game-top">
        <a href="/" className="back-link" style={{ alignSelf: 'center', color: '#8b949e', fontSize: '0.82rem', textDecoration: 'none' }}>
          &larr; Back to PanicRadar.ai
        </a>
        <button className="btn btn-small" onClick={onLobby}>
          &larr; Lobby
        </button>
        <span className="match-live-pill">Live match</span>
      </div>

      {/* ---- Match hand-off ---- */}
      {isLobby && (
        <div className="match-hud" style={{ textAlign: 'center', padding: '24px' }}>
          <p style={{ fontSize: '1.1rem', color: '#79c0ff', margin: 0 }}>
            Match accepted — preparing the board…
          </p>
        </div>
      )}

      {/* ---- Active / Complete: HUD ---- */}
      {(isActive || c.isComplete) && w && (
        <div className="match-hud">
          {/* Stats row */}
          <div className="match-hud-row match-hud-stats">
            <div className="hud-chip">
              <span className="hud-label">Street</span>
              <span className="hud-value">
                {w.street || 'ante'}
              </span>
            </div>
            <div className="hud-chip hud-chip--pot">
              <span className="hud-label">Pot</span>
              <span className="hud-value">{c.pot} cr</span>
            </div>
            <div className="hud-chip">
              <span className="hud-label">To Call</span>
              <span className="hud-value">{c.toCall} cr</span>
            </div>
            <div className="hud-chip">
              <span className="hud-label">Phase</span>
              <span className="hud-value hud-value--phase">
                {phaseLabel(c.wagerPhase, c.moveKind)}
              </span>
            </div>
            {c.countdown > 0 && (
              <div className="hud-chip hud-chip--timer">
                <span className="hud-label">Time</span>
                <span
                  className={`hud-value${c.countdown <= 10 ? ' hud-value--urgent' : ''}`}
                >
                  {c.countdown}s
                </span>
              </div>
            )}
          </div>

          {/* Player chips */}
          <div className="match-hud-row match-hud-players">
            {/* Our seat */}
            <div
              className={`player-chip player-chip--you${
                c.myCommitted > 0 ? ' player-chip--in' : ''
              }${c.canBet || c.isMyMove ? ' player-chip--active' : ''}`}
            >
              <span className="player-name">
                {c.mySeat ? c.mySeat.name : 'You'}
              </span>
              <span className="player-coins">
                {c.mySeat ? c.mySeat.coins : 0} cr
              </span>
              <span className="player-pts">
                {c.mySeat ? c.mySeat.score || 0 : 0} pts
              </span>
              {c.myCommitted > 0 && (
                <span className="player-committed">in pot {c.myCommitted}</span>
              )}
            </div>

            <div className="player-vs">VS</div>

            {/* Opponent seat */}
            <div
              className={`player-chip player-chip--agent${
                c.opponentSeat && c.opponentSeat.committed > 0
                  ? ' player-chip--in'
                  : ''
              }${
                isActive &&
                !c.isMyMove &&
                !c.canBet &&
                !c.isComplete
                  ? ' player-chip--active'
                  : ''
              }`}
            >
              <span className="player-name">
                {c.opponentSeat ? c.opponentSeat.name : 'Opponent'}
              </span>
              <span className="player-coins">
                {c.opponentSeat ? c.opponentSeat.coins : 0} cr
              </span>
              <span className="player-pts">
                {c.opponentSeat ? c.opponentSeat.score || 0 : 0} pts
              </span>
              {c.opponentSeat && c.opponentSeat.committed > 0 && (
                <span className="player-committed">
                  in pot {c.opponentSeat.committed}
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {isActive && isSwapTurn && (
        <div className={`swap-turn-banner${waitingForSwap ? ' swap-turn-banner--waiting' : ''}${c.isAnimating ? ' swap-turn-banner--resolving' : ''}`}>
          <span className="swap-turn-label">
            {c.isAnimating ? 'Resolving swap' : waitingForSwap ? 'Opponent is swapping' : 'Your swap'}
          </span>
          <strong>
            {c.isAnimating
              ? 'Coins are collapsing and cascading…'
              : waitingForSwap
              ? `${c.opponentSeat?.name || 'Opponent'} is choosing two coins`
              : 'Choose two adjacent coins that create a match'}
          </strong>
          <span className="swap-turn-time">
            {c.isAnimating
              ? 'Scoring the move…'
              : c.countdown > 0
              ? waitingForSwap
                ? `Forfeit in ${c.countdown}s`
                : `${c.countdown}s to make your swap`
              : 'Waiting for the server…'}
          </span>
        </div>
      )}

      {c.message && <div className="message">{c.message}</div>}

      {/* ---- Board ---- */}
      {(isActive || c.isComplete) && (
        <div className="board-wrap">
          <Board
            cells={c.cells}
            selected={c.selected}
            matchedIndices={c.matchedIndices}
            hintIndices={c.hintIndices}
            interactive={c.isMyMove && !c.isAnimating}
            onPick={c.handleClick}
          />
        </div>
      )}

      <p className="wager-disclaimer">
        Demo coins only &middot; no real money &middot; game of skill &middot; fold anytime
      </p>

      {/* ---- Bet modal (bottom pop-up) ---- */}
      {c.canBet && !c.settled && (
        <div className="bet-modal-overlay">
          <div className="bet-modal">
            <div className="bet-modal-head">
              <strong>Your turn to bet</strong>
              <span className="bet-modal-sub">
                {c.facing
                  ? `${c.opponentSeat?.name || 'Opponent'} raised — Call ${c.toCall} cr or Fold`
                  : 'No bet to face — Check or open with a Raise'}
              </span>
            </div>
            <div className="bet-modal-actions">
              <button
                className="btn"
                onClick={() => c.humanBet(BET_ACTION.CHECK)}
                disabled={!c.canCheck && c.facing}
              >
                Check
              </button>
              <button
                className="btn btn-primary"
                onClick={() => c.humanBet(BET_ACTION.CALL)}
                disabled={!c.facing || !c.canAffordCall}
              >
                {c.facing && !c.canAffordCall
                  ? `Can't call ${c.toCall} cr`
                  : `Call ${c.toCall} cr`}
              </button>
              <button
                className="btn"
                onClick={() => c.humanBet(BET_ACTION.RAISE, c.raiseAmount)}
                disabled={!c.canAffordRaise}
              >
                Raise {c.raiseAmount} cr
              </button>
              <button
                className="btn btn-danger"
                onClick={() => c.humanBet(BET_ACTION.FOLD)}
              >
                Fold
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ---- Game-over overlay ---- */}
      <WinnerOverlay
        session={c.session}
        onLobby={onLobby}
        onRematch={() => transport.requestRematch()}
        rematchRequestedByMe={c.rematchRequestedByMe}
        opponentRequestedRematch={c.opponentRequestedRematch}
      />
    </div>
  );
}
