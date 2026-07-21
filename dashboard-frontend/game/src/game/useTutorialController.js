/**
 * useTutorialController — ELI5 tutorial: swap → match → chain → free play.
 *
 * Teaches the match-3 basics in a zero-pressure environment:
 *   Step 0: "This is a Swap" — auto-animates a swap + match so the user sees it happen
 *   Step 1: "This is a Match" — user does the swap themselves, sees the result
 *   Step 2: "This is a Chain" — cascade explanation
 *   Step 3: Free play — swap as much as you want, score as high as you can
 *
 * No opponent, no timer, no coins at stake. Just learning by doing.
 *
 * Synchronised from protostatis/blockcoined2 (ff4d798).
 */
import { useCallback, useRef, useState } from 'react';
import GameEngine, { Cell } from '../engine/GameEngine';
import { playScoreSound } from './sound';

const T_SWAP = 300;
const T_MATCH = 400;
const T_CASCADE = 400;
const T_DEMO_HIGHLIGHT = 1200;  // pause on highlighted gems before swapping
const T_DEMO_MATCH = 1500;      // pause on matched gems so user sees the line-up

function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

/**
 * The guided steps.
 */
const STEPS = [
  {
    title: 'This is a Swap',
    instruction: 'Watch — two gems swap places and make a match!',
    tip: 'You\'ll try it yourself in the next step.',
  },
  {
    title: 'This is a Match',
    instruction: 'Now you try! Tap a glowing gem, then tap its neighbor.',
    tip: 'Only swaps that create a match will work.',
  },
  {
    title: 'This is a Chain',
    instruction: 'After gems pop, new ones fall in — they can chain for bonus points!',
    tip: 'Chains happen automatically. You just watch the combo grow.',
  },
  {
    title: 'Your Turn!',
    instruction: 'You\'ve got the basics — keep swapping to build your score.',
    tip: 'When you\'re ready, play vs the AI for a real challenge.',
  },
];

/**
 * Starter board with a guaranteed swap → match and NO initial matches.
 *
 * Positions 1 (ETH/red) and 9 (ETH/red) are orthogonal neighbors.
 * Swapping them puts ETH at row0,col1 adjacent to ETH at row0,col2,
 * creating a 3-match: row0 = _ 1 1 1.
 *
 * Verified: zero initial matches, 33 valid moves.
 */
const STARTER_BOARD = [
  2, 3, 1, 1, 4, 0, 3, 2,
  0, 1, 4, 3, 2, 3, 0, 4,
  3, 0, 2, 4, 1, 2, 4, 3,
  4, 2, 0, 3, 0, 4, 1, 2,
  1, 4, 3, 2, 3, 1, 2, 0,
  2, 0, 1, 4, 0, 3, 4, 1,
  3, 4, 2, 0, 4, 1, 3, 2,
  0, 2, 4, 1, 2, 0, 1, 3,
];

export function useTutorialController() {
  const engineRef = useRef(null);
  const lockRef = useRef(false);
  const genRef = useRef(0);
  const stepRef = useRef(0);
  const savedBoardRef = useRef(null); // board snapshot before step 0 demo

  const [cells, setCells] = useState([]);
  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState(null);
  const [hintIndices, setHintIndices] = useState([]);
  const [tutorialHighlight, setTutorialHighlight] = useState([]);
  const [message, setMessage] = useState('');
  const [score, setScore] = useState(0);
  const [matchedIndices, setMatchedIndices] = useState([]);
  const [phase, setPhase] = useState('idle');

  const syncCells = useCallback((engine) => {
    setCells(engine.cells.map((c) => ({ ...c })));
  }, []);

  const showHints = useCallback((engine, specificPair) => {
    if (specificPair) {
      setHintIndices(specificPair);
      return;
    }
    const moves = engine.getValidMoves();
    if (moves.length) {
      const partners = new Set();
      for (const [a, b] of moves) { partners.add(a); partners.add(b); }
      setHintIndices([...partners]);
    }
  }, []);

  /** Run the full cascade animation loop. Returns total points. */
  // ── Step 0 demo: auto-animate swap → match → pop ─────────────

  const runDemo = useCallback(async (gen, engine, swapA, swapB) => {
    // 1. Highlight the two gems that will swap
    setHintIndices([swapA, swapB]);
    setMessage('Watch — these two gems will swap places…');
    await delay(T_DEMO_HIGHLIGHT);
    if (genRef.current !== gen) return;

    // 2. Clear hints, perform the swap on the engine
    setHintIndices([]);
    engine.swapCells(swapA, swapB);
    syncCells(engine);

    // 3. Detect match
    const matched = engine.findMatches();
    if (matched.length === 0) {
      // Edge case: demo swap creates no match
      engine.swapCells(swapA, swapB); // swap back
      syncCells(engine);
      setStep(1);
      stepRef.current = 1;
      setHintIndices([swapA, swapB]);
      setMessage('Now you try! Swap those two gems.');
      return;
    }

    // 4. Match animation
    setTutorialHighlight(matched);
    setPhase('matching');
    const n = matched.length;
    setMessage(
      n >= 4
        ? `See? ${n} coins lined up — that's a match!`
        : 'See? 3 in a row — that\'s a match!'
    );
    await delay(T_DEMO_MATCH);
    if (genRef.current !== gen) return;

    // 5. Pop and cascade
    setTutorialHighlight([]);
    setMatchedIndices(matched);
    playScoreSound();
    await delay(T_MATCH);
    if (genRef.current !== gen) return;

    // 6. Apply gravity + fill (only for animation, we'll undo everything)
    engine.runCascadeStep(matched);
    syncCells(engine);
    setMatchedIndices([]);
    setPhase('cascading');
    await delay(T_CASCADE);
    if (genRef.current !== gen) return;

    // 7. CRITICAL: Restore the FULL pre-swap board from snapshot BEFORE any other logic
    if (savedBoardRef.current) {
      engine.cells = savedBoardRef.current.map((c) => c.clone());
      syncCells(engine);
    }
    setPhase('idle');

    // 8. Advance to step 1
    setStep(1);
    stepRef.current = 1;
    // Show the same pair as hints so the user knows which gems to swap
    setHintIndices([swapA, swapB]);
    setMessage('Now you try! Swap those same two gems.');
  }, [syncCells]);

  // ── Click handler ──────────────────────────────────────────────

  const handleClick = useCallback((index) => {
    const engine = engineRef.current;
    if (!engine || lockRef.current) return;

    const currentStep = stepRef.current;

    // ── Step 0: click during demo — skip to step 1 ──
    if (currentStep === 0) {
      // Cancel the running demo by bumping gen
      genRef.current += 1;
      // Restore board to pre-swap state from snapshot
      if (savedBoardRef.current) {
        engine.cells = savedBoardRef.current.map((c) => c.clone());
        syncCells(engine);
      }
      stepRef.current = 1;
      setStep(1);
      setTutorialHighlight([]);
      setMatchedIndices([]);
      setPhase('idle');
      // Show hints for the same swap pair
      const moves = engine.getValidMoves();
      if (moves.length) {
        const [a, b] = moves[0];
        setHintIndices([a, b]);
      }
      setMessage('Now you try! Swap those two gems.');
      return;
    }

    // ── Steps 1–3: two-tap swap ──
    lockRef.current = true;
    setSelected(null);
    setHintIndices([]);

    if (selected === null) {
      // First tap: select a gem and show its valid swap partners
      setSelected(index);
      const partners = new Set();
      for (const [a, b] of engine.getValidMoves()) {
        if (a === index) partners.add(b);
        else if (b === index) partners.add(a);
      }
      if (partners.size > 0) {
        setHintIndices([...partners]);
      }
      lockRef.current = false;
      return;
    }
    if (selected === index) {
      setSelected(null);
      lockRef.current = false;
      return;
    }

    const i = selected, j = index;
    lockRef.current = true;
    setSelected(null);
    setHintIndices([]);

    (async () => {
      const gen = genRef.current;

      // ── Phase 1: visual swap ──
      setPhase('swapping');
      engine.swapCells(i, j);
      syncCells(engine); // CSS transition animates the slide (0.28s)
      await delay(380); // wait for slide to finish
      if (genRef.current !== gen) return;

      // ── Phase 2: detect match ──
      const matched = engine.findMatches();
      if (matched.length === 0) {
        // Invalid swap — swap back
        engine.swapCells(i, j);
        syncCells(engine);
        setPhase('idle');
        setMessage('Those two don\'t make a match — try a different pair!');
        lockRef.current = false;
        return;
      }

      // ── Phase 3: match glow ──
      setTutorialHighlight(matched);
      setPhase('matching');
      await delay(T_MATCH);
      if (genRef.current !== gen) return;

      // ── Phase 4: pop + cascade ──
      setTutorialHighlight([]);
      setMatchedIndices(matched);
      playScoreSound();
      await delay(T_MATCH);
      if (genRef.current !== gen) return;
      const cascadeResult = engine.runCascadeStep(matched);
      syncCells(engine);
      setMatchedIndices([]);
      setPhase('cascading');
      await delay(T_CASCADE);
      if (genRef.current !== gen) return;

      // Handle chains
      let totalPoints = matched.length;
      let chainMatched = cascadeResult.chainMatched;
      let safety = 0;
      while (chainMatched.length > 0 && safety < 20) {
        if (genRef.current !== gen) return;
        setMatchedIndices(chainMatched);
        setPhase('matching');
        playScoreSound();
        await delay(T_MATCH);
        if (genRef.current !== gen) return;
        const nextStep = engine.runCascadeStep(chainMatched);
        totalPoints += nextStep.points;
        syncCells(engine);
        setMatchedIndices([]);
        setPhase('cascading');
        await delay(T_CASCADE);
        chainMatched = nextStep.chainMatched;
        safety++;
      }

      if (genRef.current !== gen) return;
      engine.endTurn();
      if (!engine.hasValidMoves()) {
        engine.reshuffle();
        syncCells(engine);
      }
      setScore((s) => s + totalPoints);
      setPhase('idle');

      const cs = stepRef.current;

      if (cs === 1) {
        // Step 1 → 2: show the match result, then check for chain
        setStep(2);
        stepRef.current = 2;
        setMatchedIndices([]);
        const hasChain = safety > 0; // we had chain loops
        if (hasChain) {
          setMessage('Chain! New gems fell in and matched again — free bonus points!');
        } else {
          // Search for a chain-producing move without leaving a probe board in play.
          const boardBeforeSearch = engine.cells.map((c) => c.clone());
          const nextIdBeforeSearch = engine._nextId;
          const scoreBeforeSearch = engine.score;
          let found = false;
          for (let attempt = 0; attempt < 10; attempt++) {
            engine.initBoard();
            const candidateBoard = engine.cells.map((c) => c.clone());
            const candidateNextId = engine._nextId;
            syncCells(engine);
            const moves = engine.getValidMoves();
            for (const [a, b] of moves) {
              engine.swapCells(a, b);
              const matches = engine.findMatches();
              if (matches.length > 0) {
                const firstStep = engine.runCascadeStep(matches);
                if (firstStep.chainMatched.length > 0) {
                  engine.cells = candidateBoard.map((c) => c.clone());
                  engine._nextId = candidateNextId;
                  engine.score = scoreBeforeSearch;
                  syncCells(engine);
                  showHints(engine, [a, b]);
                  setMessage('Try another swap — watch what happens after the gems pop!');
                  found = true;
                  break;
                }
                engine.cells = candidateBoard.map((c) => c.clone());
                engine._nextId = candidateNextId;
                engine.score = scoreBeforeSearch;
              }
              if (found) break;
            }
            if (found) break;
          }
          if (!found) {
            engine.cells = boardBeforeSearch;
            engine._nextId = nextIdBeforeSearch;
            engine.score = scoreBeforeSearch;
            syncCells(engine);
            setMessage('Sometimes falling gems match too — that\'s a chain combo!');
          }
        }
      } else if (cs === 2) {
        // Step 2 → 3: transition to free play
        setStep(3);
        stepRef.current = 3;
        setMatchedIndices([]);
        showHints(engine);
        setMessage('You\'ve got the basics! Keep swapping to build your score.');
      } else {
        // Step 3: free play
        setMatchedIndices([]);
        showHints(engine);
        if (totalPoints > 5) {
          setMessage(`Nice combo! ${totalPoints} points — keep going!`);
        } else if (totalPoints > 0) {
          setMessage(`${totalPoints} points — nice!`);
        } else {
          setMessage('');
        }
      }
      lockRef.current = false;
    })();
  }, [selected, syncCells, showHints]);

  // ── Lifecycle ──────────────────────────────────────────────────

  const start = useCallback(() => {
    genRef.current += 1;
    lockRef.current = false;
    const engine = new GameEngine();

    // Load the starter layout
    engine.cells = STARTER_BOARD.map((t, i) => new Cell(t, i + 1));
    engine._nextId = STARTER_BOARD.length;
    if (!engine.hasValidMoves()) {
      engine.initBoard();
    }
    engineRef.current = engine;

    setStep(0);
    stepRef.current = 0;
    setScore(0);
    setSelected(null);
    setMatchedIndices([]);
    setHintIndices([]);
    setTutorialHighlight([]);
    setPhase('idle');
    syncCells(engine);

    // Find a valid move and auto-play the demo
    const moves = engine.getValidMoves();
    if (moves.length) {
      const [a, b] = moves[0];
      // Save board snapshot so we can restore if user clicks during demo
      savedBoardRef.current = engine.cells.map((c) => c.clone());
      // Start the demo animation (non-blocking)
      runDemo(genRef.current, engine, a, b);
    } else {
      setMessage('Welcome! Tap any gem to get started.');
    }
  }, [syncCells, runDemo]);

  const reset = useCallback(() => {
    genRef.current += 1;
    lockRef.current = false;
    setCells([]);
    setStep(0);
    stepRef.current = 0;
    setSelected(null);
    setHintIndices([]);
    setTutorialHighlight([]);
    setMessage('');
    setScore(0);
    setMatchedIndices([]);
    setPhase('idle');
    engineRef.current = null;
    savedBoardRef.current = null;
  }, []);

  const skip = useCallback(() => {
    genRef.current += 1; // cancel any running demo
    setStep(3);
    stepRef.current = 3;
    setTutorialHighlight([]);
    setMatchedIndices([]);
    setPhase('idle');
    const engine = engineRef.current;
    if (engine) showHints(engine);
    setMessage('Free play — swap as much as you like!');
  }, [showHints]);

  // ── Computed UI helpers ────────────────────────────────────────

  const stepInfo = STEPS[step] || STEPS[0];
  const canAdvance = step < 3;

  return {
    cells,
    selected,
    matchedIndices,
    hintIndices,
    tutorialHighlight,
    phase,
    message,
    score,
    step,
    stepInfo,
    totalSteps: STEPS.length,
    canAdvance,
    isFreePlay: step === 3,
    start,
    reset,
    skip,
    handleClick,
  };
}
