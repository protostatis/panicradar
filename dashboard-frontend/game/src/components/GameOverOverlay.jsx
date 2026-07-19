import React from 'react';
// eslint-disable-next-line no-unused-vars
import { motion } from 'framer-motion';
import { getStandings } from '../game/sessionReducer';

export default function GameOverOverlay({ session, onPlayAgain, onMenu }) {
  if (!session || session.status !== 'finished') return null;
  const rows = getStandings(session);
  const winners = rows.filter((r) => session.winnerIds.includes(r.id));
  const title = winners.length === 0
    ? 'Draw!'
    : winners.length === 1
      ? `🏆 ${winners[0].name} wins!`
      : `Draw — tied: ${winners.map((w) => w.name).join(', ')}`;

  return (
    <motion.div
      className="game-over-overlay"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
    >
      <motion.div
        className="game-over-box"
        role="dialog"
        aria-modal="true"
        aria-labelledby="game-over-title"
        initial={{ scale: 0.6, opacity: 0, y: 40 }}
        animate={{ scale: 1, opacity: 1, y: 0 }}
        transition={{ delay: 0.15, type: 'spring', stiffness: 160, damping: 14 }}
      >
        <h1 id="game-over-title">{title}</h1>
        <ul className="final-standings">
          {rows.map((r, i) => (
            <li key={r.id}>
              <span>{i + 1}. {r.name}{r.kind === 'agent' ? ' 🤖' : ''}</span>
              <strong>{r.score}</strong>
            </li>
          ))}
        </ul>
        {session.pool > 0 && winners.length === 1 && (
          <p className="game-over-turns">{winners[0].name} takes the {session.pool} credit pool 💰</p>
        )}
        <div className="game-over-actions">
          <button className="btn btn-primary btn-large" onClick={onPlayAgain}>Play Again</button>
          <button className="btn btn-large" onClick={onMenu}>Menu</button>
        </div>
      </motion.div>
    </motion.div>
  );
}
