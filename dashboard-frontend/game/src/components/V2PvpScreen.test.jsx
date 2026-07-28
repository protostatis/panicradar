import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { PlayerCreditSummary } from './V2PvpScreen';

describe('PlayerCreditSummary', () => {
  it('distinguishes table credits from the escrow-inclusive total', () => {
    const markup = renderToStaticMarkup(
      <PlayerCreditSummary tableCredits={90} totalCredits={200} />
    );

    expect(markup).toContain('Table 90 cr');
    expect(markup).toContain('Total 200 cr');
    expect(markup).toContain('includes table');
  });
});
