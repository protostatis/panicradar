/**
 * TutorialScreen — ELI5 guided tutorial for learning match-3 basics.
 *
 * Renders the board in a zero-pressure environment with step-by-step
 * instructions that teach swap → match → chain → free play.
 * No opponent, no timer, no coins at stake.
 *
 * Synchronised from protostatis/blockcoined2 (ff4d798).
 */
import React, { useEffect } from 'react';
import Board from './Board';
import { useTutorialController } from '../game/useTutorialController';

export default function TutorialScreen({ onDone, onSkip }) {
  const c = useTutorialController();

  useEffect(() => {
    c.start();
    return () => c.reset();
  }, []); // eslint-disable-line

  return (
    <div className="game-screen tutorial-screen">
      {/* Step indicator dots */}
      <div className="tut-steps">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className={`tut-dot${c.step >= i ? ' tut-dot--active' : ''}${c.step > i ? ' tut-dot--done' : ''}`}
          />
        ))}
      </div>

      {/* Step title */}
      <h2 className="tut-title">{c.stepInfo.title}</h2>

      {/* Instruction card */}
      <div className="tut-card">
        <p className="tut-instruction">{c.stepInfo.instruction}</p>
        {c.stepInfo.tip && (
          <p className="tut-tip">{c.stepInfo.tip}</p>
        )}
      </div>

      {/* Score display (always visible once scoring starts) */}
      {c.score > 0 && (
        <div className="tut-score">
          <span className="tut-score-label">Score</span>
          <span className="tut-score-value">{c.score}</span>
        </div>
      )}

      {/* The board */}
      <div className="board-wrap">
        <Board
          cells={c.cells}
          selected={c.selected}
          matchedIndices={c.matchedIndices}
          hintIndices={c.hintIndices}
          tutorialHighlight={c.tutorialHighlight}
          interactive={true}
          onPick={c.handleClick}
        />
      </div>

      {/* Dynamic message */}
      {c.message && (
        <div className={`tut-message${c.step === 3 ? ' tut-message--free' : ''}`}>
          {c.message}
        </div>
      )}

      {/* Action buttons */}
      <div className="tut-actions">
        {c.isFreePlay ? (
          <button className="btn btn-v2 tut-play-btn" onClick={onDone}>
            Play vs AI →
          </button>
        ) : (
          <button className="btn btn-skip" onClick={onSkip}>
            Skip tutorial
          </button>
        )}
      </div>

      <p className="wager-disclaimer">No coins · No opponent · Just learning</p>
    </div>
  );
}
