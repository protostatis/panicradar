import { describe, it, expect } from 'vitest';
import { findValidSwapTargets, isCascadePresentation } from './usePvpWagerController';

function boardCells() {
  return Array.from({ length: 64 }, (_, index) => ({
    id: index,
    type: (Math.floor(index / 8) + (index % 8)) % 5,
  }));
}

describe('findValidSwapTargets', () => {
  it('highlights adjacent targets that create a match after the selected swap', () => {
    const cells = boardCells();
    cells[0].type = 1;
    cells[1].type = 2;
    cells[2].type = 1;
    cells[9].type = 1;

    expect(findValidSwapTargets(cells, 1)).toContain(9);
  });

  it('does not highlight non-adjacent or non-matching targets', () => {
    const cells = Array.from({ length: 64 }, (_, index) => ({
      id: index,
      type: (Math.floor(index / 8) + (index % 8)) % 2,
    }));
    expect(findValidSwapTargets(cells, 63)).toEqual([]);
  });
});

describe('isCascadePresentation', () => {
  it('accepts only a revision-bound server cascade trace', () => {
    const presentation = {
      kind: 'cascade',
      baseRevision: 4,
      revision: 5,
      swap: [1, 9],
      steps: [{ matchedIndices: [0, 1, 2], points: 3, afterCells: boardCells() }],
    };

    expect(isCascadePresentation(presentation, 4, 5)).toBe(true);
    expect(isCascadePresentation(presentation, 3, 5)).toBe(false);
    expect(isCascadePresentation({ ...presentation, steps: [] }, 4, 5)).toBe(false);
  });
});
