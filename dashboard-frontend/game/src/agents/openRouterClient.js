/**
 * openRouterClient.js — free-model LLM agent for "vs AI" mode.
 *
 * Calls OpenRouter chat completions directly from the browser using a
 * user-pasted key (held in memory only). To keep a small free model reliable
 * we send the board as a compact type array + the enumerated list of *valid*
 * swaps, and ask it to return ONLY the chosen candidate index. We validate
 * the reply, enforce a timeout via AbortController, and fall back to a random
 * legal move on any failure.
 */

const OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions';

// Free models rotate; make it configurable in the UI. Sensible defaults:
export const DEFAULT_MODELS = [
  'meta-llama/llama-3.2-3b-instruct:free',
  'google/gemma-2-2b-it:free',
  'mistralai/mistral-7b-instruct:free',
];

function buildPrompt(engine) {
  const board = engine.cells.map((c) => c.type); // 0..4, -1 = empty
  const valid = engine.getValidMoves(); // [[i,j], ...]
  const lines = [];
  lines.push('You are playing a match-3 game on an 8x8 board (64 cells, index 0..63, row-major).');
  lines.push('There are 5 gem types encoded as integers 0..4. -1 means empty.');
  lines.push('A "valid move" swaps two orthogonally-adjacent cells and creates at least one line of 3+ matching gems.');
  lines.push('Current board (row-major, 64 values):');
  lines.push(JSON.stringify(board));
  lines.push('Valid moves (each is [cellIndexA, cellIndexB]):');
  valid.forEach((m, idx) => lines.push(`${idx}: [${m[0]}, ${m[1]}]`));
  lines.push(`Choose the best move. Reply with ONLY the integer index (0..${valid.length - 1}) of your chosen move. No explanation.`);
  return lines.join('\n');
}

async function callModel({ apiKey, model, prompt, signal }) {
  const res = await fetch(OPENROUTER_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
      'HTTP-Referer': window.location.origin,
      'X-Title': 'BlockCoined',
    },
    body: JSON.stringify({
      model,
      messages: [{ role: 'user', content: prompt }],
      temperature: 0.2,
      max_tokens: 16,
    }),
    signal,
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`OpenRouter ${res.status}: ${txt.slice(0, 200)}`);
  }
  const data = await res.json();
  const content = data?.choices?.[0]?.message?.content ?? '';
  return content;
}

function parseIndex(content, max) {
  const m = String(content).match(/-?\d+/);
  if (!m) return null;
  const n = parseInt(m[0], 10);
  if (Number.isNaN(n) || n < 0 || n > max) return null;
  return n;
}

/**
 * Decide the agent's betting action for the current street.
 *
 * V2 guardrail: the agent may ONLY propose from a bounded, legal action set and
 * receives only the PUBLIC wager state (pot, commits, street, its own coins).
 * It never sees hidden board RNG or opponent intent. The server/local controller
 * validates the action via applyBet() before it executes — the agent can never
 * settle coins itself.
 *
 * @param {object} wager  wagering state (see game/wagering.js)
 * @param {string} agentId seat id of the agent
 * @param {object} opts { apiKey, model }
 * @returns {Promise<{action:string, amount:number, usedModel:boolean, timedOut:boolean, note?:string}>}
 */
export async function agentDecideBet(wager, agentId, { apiKey, model }) {
  const seat = wager.seats.find((s) => s.id === agentId);
  if (!seat) return { action: 'check', amount: 0, usedModel: false, timedOut: false };

  const toCall = Math.max(0, wager.currentBet - seat.committed);
  const facingBet = toCall > 0;
  const canCall = seat.coins >= toCall;
  const canRaise = wager.raiseCountThisStreet < 1 && seat.coins >= toCall + (2 * wager.pot);

  if (!apiKey) {
    // Simple deterministic persona: call/check if affordable, else fold.
    const action = facingBet ? (canCall ? 'call' : 'fold') : 'check';
    return { action, amount: 0, usedModel: false, timedOut: false };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const legal = facingBet ? ['call', 'fold'] : ['check', 'fold'];
    if (canRaise) legal.push('raise');
    const prompt = [
      'You are playing a skill-based match-3 wager (demo coins only, no real money).',
      `Street: ${wager.street}. Pot: ${wager.pot}. Your committed this round: ${seat.committed}. Current bet to match: ${wager.currentBet}.`,
      `Your coins: ${seat.coins}. You are ${facingBet ? 'facing a bet' : 'not facing a bet'}.`,
      `Legal actions: ${legal.join(', ')}. Max one raise per street.`,
      'You may raise only to increase the pot by a fixed amount. Prefer folding weak boards, calling fair ones, raising strong ones.',
      'Reply with ONLY one word: check, call, fold, or raise. No explanation.',
    ].join('\n');
    const content = await callModel({ apiKey, model, prompt, signal: controller.signal });
    const word = String(content).trim().toLowerCase().match(/check|call|fold|raise/);
    let action = word ? word[0] : (facingBet ? 'call' : 'check');
    if (action === 'raise' && !canRaise) action = facingBet ? 'call' : 'check';
    if (action === 'call' && !facingBet) action = 'check';
    if ((action === 'call' && !canCall) || (action === 'check' && facingBet)) action = canCall ? 'call' : 'fold';
    return { action, amount: 0, usedModel: true, timedOut: false };
  } catch (e) {
    const timedOut = e.name === 'AbortError';
    const action = facingBet ? (canCall ? 'call' : 'fold') : 'check';
    return { action, amount: 0, usedModel: false, timedOut, note: timedOut ? 'Agent bet timeout — safe action' : `Agent bet error — safe action (${e.message.slice(0, 40)})` };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Pick a move for the agent.
 * @returns {Promise<{i:number,j:number, usedModel:boolean, timedOut:boolean, note?:string}>}
 */
export async function agentPickMove(engine, { apiKey, model }) {
  const valid = engine.getValidMoves();
  if (valid.length === 0) {
    return { i: -1, j: -1, usedModel: false, timedOut: false, note: 'No valid moves (board reshuffled)' };
  }
  if (!apiKey) {
    const fallback = randomChoice(valid);
    return { ...fallback, usedModel: false, timedOut: false };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const prompt = buildPrompt(engine);
    const content = await callModel({ apiKey, model, prompt, signal: controller.signal });
    const idx = parseIndex(content, valid.length - 1);
    if (idx == null) {
      const fb = randomChoice(valid);
      return { ...fb, usedModel: true, timedOut: false, note: `Unparseable reply — random move. Raw: ${content.slice(0, 40)}` };
    }
    const [i, j] = valid[idx];
    return { i, j, usedModel: true, timedOut: false };
  } catch (e) {
    const fb = randomChoice(valid);
    const timedOut = e.name === 'AbortError';
    return { ...fb, usedModel: false, timedOut, note: timedOut ? 'Agent timed out — random move' : `Agent error — random move (${e.message.slice(0, 60)})` };
  } finally {
    clearTimeout(timer);
  }
}

function randomChoice(arr) {
  const pick = arr[Math.floor(Math.random() * arr.length)];
  return { i: pick[0], j: pick[1] };
}
