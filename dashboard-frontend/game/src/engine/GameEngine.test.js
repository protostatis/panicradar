import { describe, expect, it } from 'vitest';
import GameEngine from './GameEngine';

function seededRandom(seed = 123456) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

describe('GameEngine (8x8)', () => {
  it('creates a playable board without starting matches', () => {
    const engine = new GameEngine(8, seededRandom());
    expect(engine.cells).toHaveLength(64);
    expect(engine.findMatches()).toEqual([]);
    expect(engine.getValidMoves().length).toBeGreaterThan(0);
  });

  it('rejects non-adjacent and non-scoring swaps without changing the board', () => {
    const engine = new GameEngine(8, seededRandom());
    const before = engine.cells.map((cell) => cell.id);
    expect(engine.beginMove(0, 63)).toBeNull();
    expect(engine.cells.map((cell) => cell.id)).toEqual(before);

    let invalidAdjacent = null;
    for (let index = 0; index < engine.totalCells && !invalidAdjacent; index += 1) {
      const right = index + 1;
      if (engine.isValidSwap(index, right) && !engine.getValidMoves().some(([a, b]) => a === index && b === right)) {
        invalidAdjacent = [index, right];
      }
    }
    expect(invalidAdjacent).not.toBeNull();
    expect(engine.beginMove(...invalidAdjacent)).toBeNull();
    expect(engine.cells.map((cell) => cell.id)).toEqual(before);
  });

  it('resolves a valid move and all cascades', () => {
    const engine = new GameEngine(8, seededRandom());
    const [first, second] = engine.getValidMoves()[0];
    const move = engine.beginMove(first, second);
    let matches = move.matchedIndices;
    let score = 0;
    let safety = 0;
    while (matches.length > 0 && safety < 20) {
      const result = engine.runCascadeStep(matches);
      score += result.points;
      matches = result.chainMatched;
      safety += 1;
    }
    engine.endTurn();

    expect(score).toBeGreaterThanOrEqual(3);
    expect(engine.turn).toBe(1);
    expect(engine.findMatches()).toEqual([]);
    expect(engine.cells.every((cell) => cell.type >= 0 && cell.type < 5)).toBe(true);
  });

  it('returns valid moves from the getValidMoves API', () => {
    const engine = new GameEngine(8, seededRandom());
    const moves = engine.getValidMoves();
    expect(moves.length).toBeGreaterThan(0);
    for (const [a, b] of moves) {
      expect(engine.isValidSwap(a, b)).toBe(true);
      engine.swapCells(a, b);
      expect(engine.findMatches().length).toBeGreaterThan(0);
      engine.swapCells(a, b);
    }
  });
});
