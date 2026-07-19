import React, { useRef, useState } from 'react';
import { GEM_NAMES, GEM_COLORS } from '../engine/GameEngine';

import iconBtc from '../img/icon/btc.png';
import iconEth from '../img/icon/eth.png';
import iconXrp from '../img/icon/xrp.png';
import iconEos from '../img/icon/eos.png';
import iconLtc from '../img/icon/ltc.png';

const ICONS = { btc: iconBtc, eth: iconEth, xrp: iconXrp, eos: iconEos, ltc: iconLtc };

const ANGLE = 0.785398; // Math.PI / 4
const CELL = 80;
const GEM = 64;
const OX = 368;
const OY = -3;
const BOARD_SIZE = 8;

function gx(i) {
  const c = i % BOARD_SIZE, r = Math.floor(i / BOARD_SIZE);
  return OX + c * CELL * Math.cos(ANGLE) - r * CELL * Math.sin(ANGLE);
}
function gy(i) {
  const c = i % BOARD_SIZE, r = Math.floor(i / BOARD_SIZE);
  return OY + r * CELL * Math.cos(ANGLE) + c * CELL * Math.sin(ANGLE);
}

/** Find the next cell index in the given arrow-key direction (logical 8×8 grid). */
function nextIndex(index, key) {
  const row = Math.floor(index / BOARD_SIZE);
  const col = index % BOARD_SIZE;
  if (key === 'ArrowUp')    return Math.max(0, row - 1) * BOARD_SIZE + col;
  if (key === 'ArrowDown')  return Math.min(BOARD_SIZE - 1, row + 1) * BOARD_SIZE + col;
  if (key === 'ArrowLeft')  return row * BOARD_SIZE + Math.max(0, col - 1);
  if (key === 'ArrowRight') return row * BOARD_SIZE + Math.min(BOARD_SIZE - 1, col + 1);
  return index;
}

/**
 * A single gem.
 *
 * The OUTER slot is positioned by `transform: translate(x, y)` and has a CSS
 * `transition` on transform. Because the list is keyed by the engine's STABLE
 * gem id (not grid index), a gem that falls to a lower slot keeps the same
 * element and only its target position changes — so the browser slides it down
 * smoothly. The INNER element is the visual gem and handles the matched pop
 * and refill drop-in via CSS keyframes (effects only, so they never fight the
 * slot's translate).
 */
function Gem({ index, cell, selected, matched, hinted, interactive, onPick, onKeyDown, onFocus, tabIndex, gemRef }) {
  const color = GEM_COLORS[cell.type];
  const name = GEM_NAMES[cell.type];
  const icon = ICONS[name];
  const x = gx(index);
  const y = gy(index);
  const row = Math.floor(index / BOARD_SIZE) + 1;
  const col = (index % BOARD_SIZE) + 1;
  const label = `${name} gem, row ${row} column ${col}${selected ? ', selected' : ''}${hinted ? ', valid swap' : ''}`;
  return (
    <div
      className="gem-slot"
      style={{ transform: `translate(${x}px, ${y}px)` }}
    >
      <div
        ref={gemRef}
        role="button"
        tabIndex={tabIndex}
        aria-label={label}
        aria-pressed={selected}
        className={`gem ${color}${selected ? ' selected' : ''}${matched ? ' matched' : ''}${hinted ? ' hinted' : ''}`}
        onClick={interactive ? () => onPick(index) : undefined}
        onKeyDown={interactive ? onKeyDown : undefined}
        onFocus={interactive ? onFocus : undefined}
      >
        {icon && <img src={icon} alt="" className="gem-icon" draggable={false} />}
      </div>
    </div>
  );
}

export default function Board({ cells, selected, matchedIndices, hintIndices, interactive, onPick }) {
  const refs = useRef([]);
  const [focusIndex, setFocusIndex] = useState(0);
  const hints = hintIndices || [];

  const handleKeyDown = (event, index) => {
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
      event.preventDefault();
      const target = nextIndex(index, event.key);
      setFocusIndex(target);
      refs.current[target]?.focus();
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onPick(index);
    }
  };

  const gems = [];
  for (let i = 0; i < 64; i++) {
    const cell = cells[i];
    if (!cell || cell.type === -1) continue; // empty slot: nothing to render
    gems.push(
      <Gem
        key={`gem-${cell.id}`}
        index={i}
        cell={cell}
        selected={selected === i}
        matched={matchedIndices.includes(i)}
        hinted={hints.includes(i)}
        interactive={interactive}
        onPick={onPick}
        onKeyDown={(e) => handleKeyDown(e, i)}
        onFocus={() => setFocusIndex(i)}
        tabIndex={interactive && focusIndex === i ? 0 : -1}
        gemRef={(node) => { refs.current[i] = node; }}
      />
    );
  }
  return (
    <div className="board-container" aria-label="8 by 8 tilted coin board">
      <div className="board">{gems}</div>
    </div>
  );
}
