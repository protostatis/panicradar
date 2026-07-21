/**
 * useWagerController — V2 street-based wagering orchestrator (PvA-first slice).
 *
 * Owns the Hold'em-structured wager state machine for a LOCAL (vs-AI) match:
 *   postAnte -> (flop/turn/river: each seat makes ONE swap, then a betting
 *   round check/call/raise/fold) -> showdown -> settle demo-coin pot.
 *
 * It deliberately does NOT touch the PvP server or the existing self-play flow.
 * The wager logic lives in game/wagering.js (pure). This hook drives the board
 * engine, animates cascades, and routes the agent's swap + bet through the same
 * validated command path a human uses. Coins are demo-only; the agent cannot
 * settle anything itself.
 *
 * SCOPE (advisor-approved first slice): 3 streets, 1 move each, fixed ante,
 * max 1 raise/street, auto-check-or-fold on timeout, no chain, no real prizes.
 *
 * NOTE: The circular callback structure (afterBet → triggerAgentBet →
 * maybeTriggerAgentMove → triggerAgentMove → doStreetMove → ...) is intentional
 * and safe — each callback captures the latest ref via wagerRef. ESLint's
 * react-hooks/immutability rule does not model this closure pattern.
 */
/* eslint-disable react-hooks/immutability, react-hooks/exhaustive-deps */
import { useCallback, useRef, useState } from 'react';
import GameEngine from '../engine/GameEngine';
import { agentPickMove, agentDecideBet, DEFAULT_MODELS } from '../agents/openRouterClient';
import { playScoreSound } from './sound';
import {
  createWager, postAnte, recordStreetMove, applyBet, autoAct,
  currentActor, currentMoveActor, isComplete, BET_ACTION, WAGER_PHASE, DEFAULT_ANTE,
} from './wagering';

const T_SWAP = 250;
const T_MATCH = 300;
const T_CASCADE = 350;
const T_STREET_PAUSE = 500;
const T_BET_PAUSE = 450;
const TURN_TIMEOUT_MS = 60000; // auto-fold/check if the human (or agent) stalls — poker-style 60s

function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

// Random, flavorful display names so each hand feels fresh.
const HUMAN_NAMES = ['CryptoKid', 'GemHunter', 'SwapMaster', 'BlockBuster', 'CoinWizard', 'TileTitan', 'ChainChamp', 'PixelPirate', 'HashHero', 'VaultViper'];
const AGENT_NAMES = ['Halcyon', 'NebulaBot', 'Quasar', 'Volt', 'Cipher', 'Orbitron', 'Zephyr', 'Mirage', 'Pulse', 'Cobalt'];
function pickRandom(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

// ---- Persistence: keep the player's demo coins + generated name across
// games and sessions so returning players retain what they earned. ----
const NAME_KEY = 'bc2_v2_name';
const COINS_KEY = 'bc2_v2_coins';
const START_COINS = 100;

function loadPersistedName() {
  try {
    const n = localStorage.getItem(NAME_KEY);
    if (n) return n;
  } catch { /* ignore */ }
  const n = pickRandom(HUMAN_NAMES);
  try { localStorage.setItem(NAME_KEY, n); } catch { /* ignore */ }
  return n;
}
function saveName(n) {
  try { localStorage.setItem(NAME_KEY, n); } catch { /* ignore */ }
}
function loadPersistedCoins() {
  try {
    const c = localStorage.getItem(COINS_KEY);
    if (c != null) return Math.max(0, parseInt(c, 10) || 0);
  } catch { /* ignore */ }
  return null; // null = never played; use default stack
}
function saveCoins(c) {
  try { localStorage.setItem(COINS_KEY, String(Math.max(0, c | 0))); } catch { /* ignore */ }
}

export function useWagerController(opts = {}) {
  const engineRef = useRef(null);
  const lockRef = useRef(false);
  const genRef = useRef(0);
  const timerRef = useRef(null);
  const countdownRef = useRef(null);
  const wagerRef = useRef(null);

  const [cells, setCells] = useState([]);
  const [phase, setPhase] = useState('idle'); // board animation phase
  const [matchedIndices, setMatchedIndices] = useState([]);
  const [selected, setSelected] = useState(null);
  const [hintIndices, setHintIndices] = useState([]); // board cells to highlight as swap hints
  const [wager, setWager] = useState(null);
  const [session, setSession] = useState(null); // mirror of seats for Standings
  const [message, setMessage] = useState('');
  const [thinking, setThinking] = useState(false);
  const [countdown, setCountdown] = useState(0); // seconds left on the action timer
  const [lastLog, setLastLog] = useState([]);

  const agentKey = opts.agentKey || '';
  const agentModel = opts.agentModel || DEFAULT_MODELS[0];
  const agentName = opts.agentName || 'AI Agent';

  const setW = useCallback((next) => {
    // Sync accumulated match-3 points into the wager seats so the PURE machine's
    // internal showdown() reads correct scores and settles the pot ONCE (no
    // double settlement). Store the synced copy as the source of truth.
    const synced = { ...next, seats: next.seats.map((s) => ({ ...s, score: scoreRef.current[s.id] || 0 })) };
    wagerRef.current = synced;
    setWager(synced);
    setLastLog(synced.log);
    // Mirror seats into a session-like shape for the existing Standings UI.
    // `score` = accumulated match-3 points (what decides the pot); `stake` =
    // coins committed this round (shown in the wallet bar, not here).
    setSession({
      players: synced.seats.map((s) => ({ id: s.id, name: s.name, kind: s.kind, score: s.score, stake: s.committed })),
      pool: synced.pot,
      status: synced.phase === WAGER_PHASE.COMPLETE ? 'finished' : 'playing',
      winnerIds: synced.winnerIds,
    });
    // Persist the human's demo-coin balance when a hand finishes, so the
    // next game (or a return visit) resumes with what they earned.
    if (synced.phase === WAGER_PHASE.COMPLETE) {
      const human = synced.seats.find((s) => s.kind === 'human');
      if (human) saveCoins(human.coins);
    }
  }, []);

  const runCascade = useCallback(async (gen, engine, init) => {
    // Phase 1: visual swap animation
    setCells(engine.cells.map((c) => ({ ...c })));
    await delay(T_SWAP);
    if (genRef.current !== gen) return 0;

    // Phase 2: find and highlight matches
    const matched = engine.findMatches();
    if (matched.length === 0) {
      // Invalid swap - swap back for visual consistency
      engine.swapCells(init.i, init.j);
      setCells(engine.cells.map((c) => ({ ...c })));
      return 0;
    }

    // Phase 3: match highlight
    setMatchedIndices(matched);
    setPhase('matching');
    await delay(T_MATCH);
    if (genRef.current !== gen) return 0;

    // Phase 4: gem pop animation
    playScoreSound();
    await delay(T_MATCH);
    if (genRef.current !== gen) return 0;

    // Phase 5: run cascade (gravity + fill + chain detection)
    const cascadeStep = engine.runCascadeStep(matched);
    setCells(engine.cells.map((c) => ({ ...c })));
    setMatchedIndices([]);
    setPhase('cascading');
    await delay(T_CASCADE);
    if (genRef.current !== gen) return 0;

    // Phase 6: handle chain extensions
    let totalPoints = matched.length;
    let nextChain = cascadeStep.chainMatched;
    let safety = 0;
    while (nextChain.length > 0 && safety < 20) {
      if (genRef.current !== gen) return totalPoints;
      setMatchedIndices(nextChain);
      setPhase('matching');
      playScoreSound();
      await delay(T_MATCH);
      if (genRef.current !== gen) return totalPoints;
      const nextStep = engine.runCascadeStep(nextChain);
      totalPoints += nextStep.points;
      setCells(engine.cells.map((c) => ({ ...c })));
      setMatchedIndices([]);
      setPhase('cascading');
      await delay(T_CASCADE);
      nextChain = nextStep.chainMatched;
      safety++;
    }

    // Phase 7: final cleanup
    if (genRef.current !== gen) return totalPoints;
    engine.endTurn();
    if (!engine.hasValidMoves()) {
      engine.reshuffle();
      setCells(engine.cells.map((c) => ({ ...c })));
    }
    return totalPoints;
  }, []);

  // Scores accumulate per seat across streets for showdown.
  const scoreRef = useRef({});

  const clearTimer = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    if (countdownRef.current) { clearInterval(countdownRef.current); countdownRef.current = null; }
    setCountdown(0);
  }, []);

  const armTimer = useCallback(() => {
    clearTimer();
    const deadline = Date.now() + TURN_TIMEOUT_MS;
    setCountdown(Math.ceil(TURN_TIMEOUT_MS / 1000));
    countdownRef.current = setInterval(() => {
      const secs = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setCountdown(secs);
      if (secs <= 0 && countdownRef.current) { clearInterval(countdownRef.current); countdownRef.current = null; }
    }, 250);
    timerRef.current = setTimeout(() => {
      const w = wagerRef.current;
      if (!w || w.phase !== WAGER_PHASE.BETTING) return;
      const actor = currentActor(w);
      if (!actor) return;
      // Auto-action: check if free, else fold. Never raises exposure.
      const next = autoAct(w, actor.id);
      setW(next);
      setMessage(`${actor.name} timed out — auto ${w.currentBet > actor.committed ? 'fold' : 'check'}.`);
      afterBet(next);
    }, TURN_TIMEOUT_MS);
  }, [clearTimer, setW]);

  // Called after any betting action resolves; advances the machine if needed.
  const afterBet = useCallback((w) => {
    if (isComplete(w)) {
      // Pot already settled correctly: the pure machine's showdown() read the
      // match-3 points synced into w.seats[].score, so the winner is decided by
      // skill (a folded seat can never win — handled inside showdown).
      clearTimer();
      const final = wagerRef.current;
      const winnerName = final.seats.find((s) => final.winnerIds.includes(s.id))?.name || 'No one';
      const share = final.winnerIds.length ? Math.floor(final.pot / final.winnerIds.length) : 0;
      const winningPts = final.winnerIds.length ? (scoreRef.current[final.winnerIds[0]] || 0) : 0;
      setMessage(
        final.winnerIds.length === 1
          ? `${winnerName} wins the pot with ${winningPts} match points (+${share} cr).`
          : `Pot split — tied at ${winningPts} match points each (+${share} cr).`
      );
      scoreRef.current = {};
      return;
    }
    // If betting finished and advanced to a new street, the board move phase is
    // active again — let the next seat (or agent) act.
    const actor = currentActor(w);
    if (w.phase === WAGER_PHASE.BETTING && actor) {
      armTimer();
      if (actor.kind === 'agent') triggerAgentBet(w);
      return;
    }
    if (w.phase === WAGER_PHASE.STREET_MOVE) {
      if (w.moveKind === 'river_bonus') {
        setMessage('River raise called — one final bonus swap each, then showdown.');
      }
      maybeTriggerAgentMove(w);
    }
  }, [armTimer, clearTimer]);

  // ---- Human swap (street move) ----
  const doStreetMove = useCallback((actorId, i, j) => {
    const gen = genRef.current;
    const engine = engineRef.current;
    const w = wagerRef.current;
    if (!engine || !w || lockRef.current) return;
    if (w.phase !== WAGER_PHASE.STREET_MOVE) return;
    const active = currentMoveActor(w);
    if (!active || active.id !== actorId) return;

    lockRef.current = true;
    setPhase('swapping');
    setSelected(null);
    setHintIndices([]);
    const init = engine.beginMove(i, j);
    if (!init) {
      setCells(engine.cells.map((c) => ({ ...c })));
      setPhase('idle');
      setMessage('No match — try a different swap');
      lockRef.current = false;
      return;
    }
    (async () => {
      const points = await runCascade(gen, engine, init);
      if (genRef.current !== gen) return;
      engine.endTurn();
      scoreRef.current[actorId] = (scoreRef.current[actorId] || 0) + (points || 0);
       const next = recordStreetMove(w, actorId, scoreRef.current);
       setW(next);
       setPhase('idle');
       lockRef.current = false;
       if (actorId === 'human') {
         try { localStorage.setItem('bc2_v2_tutorial_done', '1'); } catch { /* ignore */ }
         setHintIndices([]);
       }
       if (next.phase === WAGER_PHASE.BETTING || isComplete(next)) {
         afterBet(next);
       } else {
         maybeTriggerAgentMove(next);
       }
    })();
  }, [runCascade, setW, afterBet]);

  const maybeTriggerAgentMove = useCallback(async (w) => {
    if (!w || w.phase !== WAGER_PHASE.STREET_MOVE) return;
    const seat = currentMoveActor(w);
    // Only clear hints when it actually becomes the agent's turn to move.
    if (seat && seat.kind === 'agent' && !seat.folded) setHintIndices([]);
    const gen = genRef.current;
    if (seat && seat.kind === 'agent' && !seat.folded) {
      // Brief beat so the player's cascade resolves and the turn change reads
      // clearly before the agent starts swapping.
      await delay(T_STREET_PAUSE);
      if (genRef.current !== gen) return;
      triggerAgentMove(w);
    }
  }, []);

  const triggerAgentMove = useCallback(async (w) => {
    const gen = genRef.current;
    const engine = engineRef.current;
    if (!engine) return;
    setThinking(true);
    setMessage(`${agentName} is plotting a swap…`);
    const res = await agentPickMove(engine, { apiKey: agentKey, model: agentModel });
    if (genRef.current !== gen) { setThinking(false); return; }
    let init = engine.beginMove(res.i, res.j);
    if (!init) {
      const valid = engine.getValidMoves();
      if (valid.length === 0) { setThinking(false); setPhase('idle'); lockRef.current = false; return; }
      const [a, b] = valid[Math.floor(Math.random() * valid.length)];
      init = engine.beginMove(a, b);
    }
    setThinking(false);
    setMessage(res.note || '');
    doStreetMoveAgent(gen, engine, w, 'agent', init);
  }, [agentKey, agentModel, agentName]);

  const doStreetMoveAgent = useCallback(async (gen, engine, w, actorId, init) => {
    lockRef.current = true;
    setPhase('swapping');
    const points = await runCascade(gen, engine, init);
    if (genRef.current !== gen) return;
    engine.endTurn();
    scoreRef.current[actorId] = (scoreRef.current[actorId] || 0) + (points || 0);
    const next = recordStreetMove(w, actorId, scoreRef.current);
    setW(next);
    setPhase('idle');
    lockRef.current = false;
    if (next.phase === WAGER_PHASE.BETTING || isComplete(next)) afterBet(next);
    else maybeTriggerAgentMove(next);
  }, [runCascade, setW, afterBet, maybeTriggerAgentMove]);

  // ---- Betting ----
  const humanBet = useCallback((action, amount = 0) => {
    const w = wagerRef.current;
    if (!w || w.phase !== WAGER_PHASE.BETTING) return;
    const actor = currentActor(w);
    if (!actor || actor.kind !== 'human') return;
    const next = applyBet(w, actor.id, action, amount);
    setW(next);
    clearTimer();
    afterBet(next);
  }, [setW, clearTimer, afterBet]);

  const triggerAgentBet = useCallback(async (w) => {
    const gen = genRef.current;
    setThinking(true);
    setMessage(`${agentName} is deciding its bet…`);
    const res = await agentDecideBet(w, 'agent', { apiKey: agentKey, model: agentModel });
    if (genRef.current !== gen) { setThinking(false); return; }
    setThinking(false);
    const next = applyBet(w, 'agent', res.action, res.amount || 0);
    setW(next);
    setMessage(res.note || `${agentName}: ${res.action}`);
    afterBet(next);
  }, [agentKey, agentModel, agentName, setW, afterBet]);

  // ---- Lifecycle ----
  const start = useCallback((playerName) => {
    genRef.current += 1;
    lockRef.current = false;
    clearTimer();
    scoreRef.current = {};
    const engine = new GameEngine();
    engineRef.current = engine;
    // Persist the player identity: if a name was passed in use it (and save
    // it); otherwise reuse the previously generated name, creating + saving
    // one on first ever play.
    let humanName = playerName || '';
    if (humanName) saveName(humanName);
    else humanName = loadPersistedName();
    const botName = opts.agentName || pickRandom(AGENT_NAMES);
    // Resume the player's demo-coin balance instead of always resetting to 100.
    const persisted = loadPersistedCoins();
    // Credit backstop: a returning player who is broke (0 / below the ante and
    // thus unable to post) is topped back up to a fresh stack so the game
    // stays playable instead of stranding them at $0.
    const broke = persisted != null && persisted < DEFAULT_ANTE;
    const startingCoins = persisted == null || broke ? START_COINS : persisted;
    const w = createWager({
      players: [
        { id: 'human', name: humanName, kind: 'human' },
        { id: 'agent', name: botName, kind: 'agent' },
      ],
      startingCoins,
    });
    const withAnte = postAnte(w);
    setW(withAnte);
    setCells(engine.cells.map((c) => ({ ...c })));
    setPhase('idle');
    setMatchedIndices([]);
    setSelected(null);
    setHintIndices([]);
    // First-time tutorial: auto-highlight one valid swap so new players learn
    // the mechanic. Flag is stored in localStorage so it only shows once ever.
    const TUT_KEY = 'bc2_v2_tutorial_done';
    let tutorial = false;
    try { tutorial = !localStorage.getItem(TUT_KEY); } catch { tutorial = false; }
    const backstopMsg = broke
      ? `Out of credits — topped back up to ${START_COINS}. `
      : '';
    if (tutorial) {
      const moves = engine.getValidMoves();
      if (moves.length) {
        const [a, b] = moves[0];
        setHintIndices([a, b]);
        setMessage(backstopMsg + 'Tap a glowing coin, then a glow to swap it — line up 3+ to score. (Tutorial)');
      } else {
        setMessage(backstopMsg + 'Ante posted. Flop — make your move.');
      }
    } else {
      setMessage(backstopMsg + 'Ante posted. Flop — make your move.');
    }
    // First mover: human (seat 0) by design to avoid first-mover advantage bias.
    if (withAnte.phase === WAGER_PHASE.BETTING) afterBet(withAnte);
    else maybeTriggerAgentMove(withAnte);
  }, [agentName, setW, afterBet, maybeTriggerAgentMove, clearTimer]);

  const reset = useCallback(() => {
    genRef.current += 1;
    lockRef.current = false;
    clearTimer();
    scoreRef.current = {};
    setWager(null);
    wagerRef.current = null;
    setSession(null);
    setCells([]);
    setPhase('idle');
    setMessage('');
    setSelected(null);
    setMatchedIndices([]);
    setLastLog([]);
  }, [clearTimer]);

  // Compute the indices of valid swap PARTNERS for a given cell, using the
  // engine's own valid-move list (so hints always match real matches).
  const hintPartners = useCallback((index) => {
    const engine = engineRef.current;
    if (!engine) return [];
    const partners = new Set();
    for (const [a, b] of engine.getValidMoves()) {
      if (a === index) partners.add(b);
      else if (b === index) partners.add(a);
    }
    return [...partners];
  }, []);

  const handleClick = useCallback((index) => {
    const w = wagerRef.current;
    if (!w || w.phase !== WAGER_PHASE.STREET_MOVE || lockRef.current) return;
    const seat = currentMoveActor(w);
    if (!seat || seat.kind !== 'human') return; // only human clicks the board
    if (selected === null) {
      setSelected(index);
      setPhase('selected');
      // On selection, highlight the adjacent coins that form a valid swap.
      setHintIndices(hintPartners(index));
      return;
    }
    if (selected === index) { setSelected(null); setPhase('idle'); setHintIndices([]); return; }
    const i = selected, j = index;
    doStreetMove('human', i, j);
  }, [selected, doStreetMove, hintPartners]);

  // True whenever it is the agent's turn to act — covers BOTH the LLM "thinking"
  // sub-state AND the swap/bet execution (where `thinking` is already false but
  // the board is still resolving the agent's move). Used to show a clear
  // "AI is making a move" indicator so the human doesn't think the game froze.
  const agentActing = (() => {
    if (!wager || isComplete(wager)) return false;
    if (wager.phase === WAGER_PHASE.STREET_MOVE) {
      return currentMoveActor(wager)?.kind === 'agent';
    }
    if (wager.phase === WAGER_PHASE.BETTING) {
      return currentActor(wager)?.kind === 'agent';
    }
    return false;
  })();

  return {
    cells, phase, matchedIndices, selected, hintIndices, wager, session, message,
    thinking, agentActing, lastLog, countdown,
    start, reset, handleClick, humanBet,
    canBet: wager && !isComplete(wager) && wager.phase === WAGER_PHASE.BETTING && currentActor(wager)?.kind === 'human',
    currentBet: wager ? wager.currentBet : 0,
    pot: wager ? wager.pot : 0,
    street: wager ? wager.street : null,
    moveKind: wager ? wager.moveKind : null,
    wagerPhase: wager ? wager.phase : null,
    seats: wager ? wager.seats : [],
    humanSeat: wager ? wager.seats.find((s) => s.kind === 'human') : null,
    agentSeat: wager ? wager.seats.find((s) => s.kind === 'agent') : null,
    // Raise is always 2x the current pot; expose so the UI shows the real number.
    raiseAmount: wager ? Math.max(0, 2 * wager.pot) : 0,
    BET_ACTION,
  };
}
