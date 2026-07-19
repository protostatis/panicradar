/**
 * usePvpWagerController — V2 PvP wagering hook (read-only client mirror).
 *
 * Subscribes to V2PvpTransport V2_SNAPSHOT messages and derives all UI state
 * from the authoritative server snapshot. Presentation-only server cascade
 * traces animate the board locally; no game rules or betting mutations run
 * client-side.
 *
 * The hook tracks only a 2-tap selected board index; all game logic
 * (match-3, wagering state machine, settlement) is owned by the server.
 *
 * Guest-only adaptation: no Google auth, no persistent identity.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { WAGER_PHASE, BET_ACTION } from './wagering';
import { playScoreSound } from './sound';

const BOARD_SIZE = 8;
const T_SWAP = 250;
const T_MATCH = 300;
const T_CASCADE = 350;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function copyCells(cells) {
  return (cells || []).map((cell) => ({ type: cell.type, id: cell.id }));
}

function swappedCells(cells, [i, j]) {
  const next = copyCells(cells);
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

/** Validate a server presentation trace before using it to animate the board. */
export function isCascadePresentation(presentation, baseRevision, revision) {
  if (
    !presentation ||
    presentation.kind !== 'cascade' ||
    presentation.baseRevision !== baseRevision ||
    presentation.revision !== revision ||
    !Array.isArray(presentation.swap) ||
    presentation.swap.length !== 2 ||
    !presentation.swap.every((index) => Number.isInteger(index) && index >= 0 && index < 64) ||
    !Array.isArray(presentation.steps) ||
    presentation.steps.length === 0
  ) return false;

  return presentation.steps.every((step) => (
    Array.isArray(step.matchedIndices) &&
    step.matchedIndices.every((index) => Number.isInteger(index) && index >= 0 && index < 64) &&
    Number.isFinite(step.points) &&
    Array.isArray(step.afterCells) &&
    step.afterCells.length === 64
  ));
}

function createsMatchAfterSwap(cells, i, j) {
  const types = cells.map((cell) => cell?.type ?? -1);
  [types[i], types[j]] = [types[j], types[i]];

  const hasLine = (index, rowStep, columnStep) => {
    const type = types[index];
    if (type === -1) return false;
    const row = Math.floor(index / BOARD_SIZE);
    const column = index % BOARD_SIZE;
    let count = 1;

    for (const direction of [-1, 1]) {
      let nextRow = row + rowStep * direction;
      let nextColumn = column + columnStep * direction;
      while (
        nextRow >= 0 && nextRow < BOARD_SIZE &&
        nextColumn >= 0 && nextColumn < BOARD_SIZE &&
        types[nextRow * BOARD_SIZE + nextColumn] === type
      ) {
        count++;
        nextRow += rowStep * direction;
        nextColumn += columnStep * direction;
      }
    }
    return count >= 3;
  };

  return [i, j].some((index) => hasLine(index, 0, 1) || hasLine(index, 1, 0));
}

/** Return adjacent target cells that create a match from a selected source. */
export function findValidSwapTargets(cells, index) {
  if (!cells[index] || cells[index].type === -1) return [];

  const row = Math.floor(index / BOARD_SIZE);
  const column = index % BOARD_SIZE;
  const candidates = [
    row > 0 ? index - BOARD_SIZE : null,
    row < BOARD_SIZE - 1 ? index + BOARD_SIZE : null,
    column > 0 ? index - 1 : null,
    column < BOARD_SIZE - 1 ? index + 1 : null,
  ].filter(Number.isInteger);

  return candidates.filter((candidate) => createsMatchAfterSwap(cells, index, candidate));
}

/**
 * @param {object} opts
 * @param {import('../transports/v2PvpTransport').V2PvpTransport} opts.transport
 * @param {string} opts.myId — the guest's server-issued userId
 */
export function usePvpWagerController({ transport, myId }) {
  const genRef = useRef(0);
  const initialSnapshot = transport?.lastSnapshot || null;
  const cellsRef = useRef(copyCells(initialSnapshot?.cells));
  const displayRevisionRef = useRef(initialSnapshot?.revision ?? -1);
  const authoritativeRevisionRef = useRef(initialSnapshot?.revision ?? -1);
  const animatingRef = useRef(false);

  // ---- Snapshot-mirrored state ----
  const [cells, setCells] = useState(() => copyCells(initialSnapshot?.cells));
  const [wager, setWager] = useState(() => initialSnapshot?.wager || null);
  const [snap, setSnap] = useState(initialSnapshot); // raw latest snapshot
  const [message, setMessage] = useState('');
  const [countdown, setCountdown] = useState(0);
  const [phase, setPhase] = useState('idle');
  const [matchedIndices, setMatchedIndices] = useState([]);
  const [isAnimating, setIsAnimating] = useState(false);

  // ---- Local-only state ----
  const [selected, setSelected] = useState(null);
  const hintIndices = selected === null ? [] : findValidSwapTargets(cells, selected);

  // ---- Derived from snapshot ----
  const lifecycle = snap?.lifecycle || 'lobby';
  const revision = snap?.revision ?? -1;
  const self = snap?.self || null;
  const players = snap?.players || [];
  const viewerId = self?.id || myId;
  const rematchRequestIds = snap?.rematch?.requestedSeatIds || [];
  const rematchRequestedByMe = rematchRequestIds.includes(viewerId);
  const opponentRequestedRematch = rematchRequestIds.some((id) => id !== viewerId);

  // Our seat index in the wager.seats array (from server-assigned self.seat).
  const mySeatIndex = self?.seat ?? -1;
  const activeSeatId = snap?.activeSeatId || null;

  const seats = wager?.seats || [];
  const mySeat = mySeatIndex >= 0 ? seats[mySeatIndex] || null : null;
  const opponentSeat = seats.find(
    (s, i) => i !== mySeatIndex && !s.folded
  ) || seats.find((s, i) => i !== mySeatIndex) || null;

  // ---- Turn detection ----
  const isMyMove =
    lifecycle === 'active' &&
    wager?.phase === WAGER_PHASE.STREET_MOVE &&
    activeSeatId === viewerId;

  const canBet =
    lifecycle === 'active' &&
    wager?.phase === WAGER_PHASE.BETTING &&
    activeSeatId === viewerId &&
    !isAnimating;

  const isComplete = lifecycle === 'complete' || wager?.phase === WAGER_PHASE.COMPLETE;

  // ---- Betting helpers ----
  const currentBet = wager?.currentBet ?? 0;
  const myCommitted = mySeat?.committed ?? 0;
  const toCall = canBet ? Math.max(0, currentBet - myCommitted) : 0;
  const raiseAmount = wager ? Math.max(0, 2 * wager.pot) : 0;
  const facing = canBet && toCall > 0;
  const canCheck = canBet && toCall === 0;
  const canAffordCall = canBet && mySeat && mySeat.coins >= toCall;
  const canAffordRaise =
    canBet &&
    mySeat &&
    mySeat.coins >= toCall + raiseAmount &&
    (wager?.raiseCountThisStreet ?? 0) < 1;

  // agentActing is always false in PvP (no AI agent)
  const agentActing = false;

  // ---- Session-like object for Standings component ----
  const session = wager
    ? {
        players: wager.seats.map((s) => ({
          id: s.id,
          name: s.name,
          kind: s.kind || 'human',
          score: s.score || 0,
          stake: s.committed || 0,
        })),
        pool: wager.pot || 0,
        status: isComplete ? 'finished' : 'playing',
        winnerIds: wager.winnerIds || [],
      }
    : null;

  // ---- Countdown from absolute deadline ----
  const deadlineRef = useRef(null);

  useEffect(() => {
    const d = snap?.deadline;
    if (!d || lifecycle !== 'active') {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCountdown(0);
      deadlineRef.current = null;
      return;
    }
    deadlineRef.current = d;

    const tick = () => {
      const rem = Math.max(0, Math.ceil((deadlineRef.current - Date.now()) / 1000));
      setCountdown(rem);
      if (rem <= 0) {
        setCountdown(0);
      }
    };

    tick(); // initial
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, [snap?.deadline, snap?.revision, lifecycle]);

  // ---- Transport subscription ----
  useEffect(() => {
    if (!transport) return;

    const setDisplayedCells = (nextCells) => {
      const copy = copyCells(nextCells);
      cellsRef.current = copy;
      setCells(copy);
    };

    const runPresentation = async (generation, presentation, finalCells, revision) => {
      animatingRef.current = true;
      setIsAnimating(true);
      setDisplayedCells(swappedCells(cellsRef.current, presentation.swap));
      setMatchedIndices([]);
      setPhase('swapping');
      await delay(T_SWAP);

      for (const step of presentation.steps) {
        if (genRef.current !== generation) return;
        setMatchedIndices(step.matchedIndices);
        setPhase('matching');
        await delay(T_MATCH);
        if (genRef.current !== generation) return;

        if (step.points > 0) playScoreSound();
        setDisplayedCells(step.afterCells);
        setMatchedIndices([]);
        setPhase('cascading');
        await delay(T_CASCADE);
      }

      if (genRef.current !== generation) return;
      setDisplayedCells(finalCells);
      setMatchedIndices([]);
      setPhase('idle');
      displayRevisionRef.current = revision;
      animatingRef.current = false;
      setIsAnimating(false);
    };

    const applySnapshot = (msg) => {
      const previousRevision = authoritativeRevisionRef.current;
      if (!Number.isInteger(msg.revision) || msg.revision < previousRevision) return;

      setSnap(msg);
      setWager(msg.wager || null);
      setMessage('');
      setSelected(null);

      // Repeated snapshots must not restart or interrupt an in-flight trace.
      if (msg.revision === previousRevision) {
        if (!animatingRef.current) {
          setDisplayedCells(msg.cells);
          displayRevisionRef.current = msg.revision;
        }
        return;
      }

      const canAnimate = (
        !animatingRef.current &&
        displayRevisionRef.current === previousRevision &&
        isCascadePresentation(msg.presentation, previousRevision, msg.revision)
      );
      authoritativeRevisionRef.current = msg.revision;

      if (!canAnimate) {
        genRef.current += 1;
        animatingRef.current = false;
        setIsAnimating(false);
        setMatchedIndices([]);
        setPhase('idle');
        setDisplayedCells(msg.cells);
        displayRevisionRef.current = msg.revision;
        return;
      }

      const generation = genRef.current + 1;
      genRef.current = generation;
      runPresentation(generation, msg.presentation, msg.cells, msg.revision);
    };

    if (transport.lastSnapshot) applySnapshot(transport.lastSnapshot);

    const off = transport.onMessage((msg) => {
      if (msg.type === 'V2_SNAPSHOT') {
        applySnapshot(msg);
      } else if (msg.type === 'ERROR') {
        setMessage(msg.message || 'An error occurred');
      } else if (msg.type === 'SYSTEM') {
        setMessage(msg.text || '');
      }
    });

    return () => {
      genRef.current += 1;
      animatingRef.current = false;
      off();
    };
  }, [transport]);

  // ---- Board click (2-tap swap → V2_MOVE) ----
  const handleClick = useCallback(
    (index) => {
      if (!isMyMove || isAnimating || !transport) return;

      if (selected === null) {
        setSelected(index);
        return;
      }
      if (selected === index) {
        setSelected(null);
        return;
      }

      if (!findValidSwapTargets(cells, selected).includes(index)) {
        setSelected(index);
        return;
      }

      const i = selected;
      const j = index;
      setSelected(null);
      transport.move(i, j);
    },
    [cells, isAnimating, isMyMove, selected, transport]
  );

  // ---- Bet action ----
  const humanBet = useCallback(
    (action) => {
      if (!canBet || !transport) return;
      transport.bet(action);
    },
    [canBet, transport]
  );

  // ---- Derived values ----
  const pot = wager?.pot ?? 0;
  const street = wager?.street ?? null;
  const moveKind = wager?.moveKind ?? null;
  const wagerPhase = wager?.phase ?? null;
  const wagerLog = wager?.log ?? [];
  const winnerIds = wager?.winnerIds ?? [];
  const settled = wager?.settled ?? false;

  return {
    // Board state
    cells,
    selected,
    matchedIndices,
    hintIndices,
    phase,
    // Wager state
    wager,
    snap,
    session,
    lifecycle,
    revision,
    // Derived
    mySeat,
    opponentSeat,
    seats,
    players,
    self,
    isMyMove,
    canBet,
    isComplete,
    isAnimating,
    rematchRequestedByMe,
    opponentRequestedRematch,
    // Betting
    currentBet,
    toCall,
    raiseAmount,
    facing,
    canCheck,
    canAffordCall,
    canAffordRaise,
    pot,
    street,
    moveKind,
    wagerPhase,
    myCommitted,
    // Meta
    message,
    countdown,
    agentActing,
    wagerLog,
    winnerIds,
    settled,
    // Actions
    handleClick,
    humanBet,
    // Constants
    BET_ACTION,
    WAGER_PHASE,
  };
}
