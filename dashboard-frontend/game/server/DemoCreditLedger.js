/**
 * DemoCreditLedger.js — in-memory demo credit ledger.
 *
 * Models the future Solana/NEAR escrow mapping:
 *   - Each guest starts with a fixed demo balance of 100.
 *   - `reserve` moves credits into a match escrow (atomic).
 *   - `settle` distributes escrowed credits to final seat balances.
 *   - `refund` returns unreserved escrowed credits.
 *   - Match IDs prevent duplicate settlement/refund.
 *
 * All behaviour is deterministic. No client-provided balance is trusted.
 */

/** @typedef {{ balance: number, escrows: Map<string, number> }} Account */

export class DemoCreditLedger {
  constructor(initialBalance = 100) {
    this._initialBalance = initialBalance;
    /** @type {Map<string, Account>} */
    this._accounts = new Map();
    /** @type {Map<string, { matchId: string, reserves: Map<string, number>, settled: boolean, refunded: boolean }>} */
    this._escrows = new Map();
  }

  /* ------------------------------------------------------------------ */
  /*  Internal helpers                                                   */
  /* ------------------------------------------------------------------ */

  _ensureAccount(id) {
    if (!this._accounts.has(id)) {
      this._accounts.set(id, { balance: this._initialBalance, escrows: new Map() });
    }
    return this._accounts.get(id);
  }

  /* ------------------------------------------------------------------ */
  /*  Public API                                                         */
  /* ------------------------------------------------------------------ */

  /** Available (non-reserved) balance for a user. */
  getBalance(id) {
    const acct = this._accounts.get(id);
    if (!acct) return this._initialBalance;
    return acct.balance;
  }

  /** Credits currently reserved for this account in one match. */
  getEscrowedBalance(id, matchId) {
    const acct = this._accounts.get(id);
    return acct?.escrows.get(matchId) || 0;
  }

  /** Restore a broke demo account before it attempts a new match escrow. */
  ensurePlayable(id, minimum) {
    const acct = this._ensureAccount(id);
    if (acct.balance < minimum && acct.escrows.size === 0) {
      acct.balance = this._initialBalance;
    }
    return acct.balance;
  }

  /**
   * Check whether a user can reserve `amount` credits.
   * Returns true if the user has >= amount available.
   */
  canReserve(id, amount) {
    const acct = this._accounts.get(id);
    if (!acct) return this._initialBalance >= amount;
    return acct.balance >= amount;
  }

  /**
   * Reserve `amount` credits from a user for a given match.
   * Returns { ok: true } or { ok: false, error: string }.
   * Idempotent: if this user already has a reserve for this match, returns ok.
   */
  reserve(id, amount, matchId) {
    if (!matchId) return { ok: false, error: 'matchId required' };

    let escrow = this._escrows.get(matchId);
    if (escrow) {
      // already exists — reject if settled/refunded, or if idempotent
      if (escrow.settled || escrow.refunded) {
        return { ok: false, error: `escrow ${matchId} already ${escrow.settled ? 'settled' : 'refunded'}` };
      }
      if (escrow.reserves.has(id)) return { ok: true }; // idempotent
    }

    const acct = this._ensureAccount(id);
    if (acct.balance < amount) {
      return { ok: false, error: `insufficient balance: ${acct.balance} < ${amount}` };
    }

    acct.balance -= amount;
    acct.escrows.set(matchId, amount);

    if (!escrow) {
      escrow = {
        matchId,
        reserves: new Map([[id, amount]]),
        settled: false,
        refunded: false,
      };
      this._escrows.set(matchId, escrow);
    } else {
      escrow.reserves.set(id, amount);
    }

    return { ok: true };
  }

  /**
   * Refund an unreserved escrow back to all participants.
   * Only works on unsettled/unrefunded escrows.
   */
  refund(matchId) {
    const escrow = this._escrows.get(matchId);
    if (!escrow) return { ok: false, error: `escrow ${matchId} not found` };
    if (escrow.settled) return { ok: false, error: `escrow ${matchId} already settled` };
    if (escrow.refunded) return { ok: false, error: `escrow ${matchId} already refunded` };

    escrow.refunded = true;
    for (const [id, amount] of escrow.reserves) {
      const acct = this._accounts.get(id);
      if (acct) {
        acct.balance += amount;
        acct.escrows.delete(matchId);
      }
    }
    return { ok: true };
  }

  /**
   * Settle an escrow: distribute credits according to final seat balances.
   *
   * @param {string} matchId
   * @param {Record<string, number>} payouts  —  { [playerId]: finalCoins }
   */
  settle(matchId, payouts) {
    const escrow = this._escrows.get(matchId);
    if (!escrow) return { ok: false, error: `escrow ${matchId} not found` };
    if (escrow.settled) return { ok: false, error: `escrow ${matchId} already settled` };
    if (escrow.refunded) return { ok: false, error: `escrow ${matchId} already refunded` };

    escrow.settled = true;

    for (const [id, _amount] of escrow.reserves) {
      const acct = this._accounts.get(id);
      if (acct) acct.escrows.delete(matchId);
    }

    for (const [id, payout] of Object.entries(payouts)) {
      const acct = this._ensureAccount(id);
      acct.balance += payout;
    }

    return { ok: true };
  }

  /**
   * Get all escrow reserves for a match (for debugging/tests).
   * Returns null if the escrow doesn't exist.
   */
  _getEscrowReserves(matchId) {
    const escrow = this._escrows.get(matchId);
    if (!escrow) return null;
    const out = {};
    for (const [id, amt] of escrow.reserves) out[id] = amt;
    return out;
  }
}

export default DemoCreditLedger;
