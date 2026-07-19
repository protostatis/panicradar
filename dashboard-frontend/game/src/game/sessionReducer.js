/**
 * sessionReducer — authoritative competition state for all game modes.
 *
 * The GameEngine owns ONLY board mechanics (swaps, matches, gravity, refill).
 * This reducer owns players, scores, turn ownership, move limits, stakes and
 * the winner. Modes are just configurations + a few pure helpers, so there is
 * a single source of truth for "who is winning".
 *
 * Events:
 *   INIT        { session }            -> replace whole session (used by transport hydration)
 *   ADD_PLAYER  { player }
 *   REMOVE_PLAYER { playerId }
 *   SET_ACTIVE  { index }
 *   MOVE_RESOLVED { actorId, points }  -> credit the actor, advance the queue, bump move count
 *   SET_LIMIT   { moveLimit }
 *   FINISH      { winnerIds }
 *   RESET
 */

export const STATUS = { PLAYING: 'playing', FINISHED: 'finished' };

export function createSession({ mode, players = [], moveLimit = null, rounds = 1 }) {
  const list = players.map((p) => ({
    id: p.id,
    name: p.name,
    kind: p.kind || 'human', // 'human' | 'agent'
    score: 0,
    stake: p.stake || 0,
  }));
  // Derive a fair move limit: every player gets `rounds` moves in turn order.
  if (moveLimit == null && list.length > 0) {
    moveLimit = rounds * list.length;
  }
  return {
    id: `sess-${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
    mode,
    players: list,
    activePlayerIndex: 0,
    completedMoves: 0,
    moveLimit, // null => endless (self-play)
    status: STATUS.PLAYING,
    winnerIds: [],
    pool: list.reduce((s, p) => s + (p.stake || 0), 0),
  };
}

export function getActivePlayer(session) {
  return session.players[session.activePlayerIndex] || null;
}

export function canAct(session, actorId) {
  if (session.status !== STATUS.PLAYING) return false;
  const active = getActivePlayer(session);
  return !!active && active.id === actorId;
}

export function getStandings(session) {
  return [...session.players]
    .map((p) => ({ id: p.id, name: p.name, kind: p.kind, score: p.score, stake: p.stake }))
    .sort((a, b) => b.score - a.score);
}

function computeWinners(session) {
  if (session.players.length === 0) return [];
  const max = Math.max(...session.players.map((p) => p.score));
  if (max === 0 && session.players.length > 1) {
    // tie at zero — call it a draw (no winners) unless it's solo self-play
    return session.players.length === 1 ? [session.players[0].id] : [];
  }
  return session.players.filter((p) => p.score === max).map((p) => p.id);
}

export function sessionReducer(session, event) {
  switch (event.type) {
    case 'INIT':
      return event.session;

    case 'ADD_PLAYER':
      return {
        ...session,
        players: [...session.players, {
          id: event.player.id,
          name: event.player.name,
          kind: event.player.kind || 'human',
          score: 0,
          stake: event.player.stake || 0,
        }],
        pool: session.pool + (event.player.stake || 0),
      };

    case 'REMOVE_PLAYER':
      return {
        ...session,
        players: session.players.filter((p) => p.id !== event.playerId),
      };

    case 'SET_ACTIVE':
      return { ...session, activePlayerIndex: event.index };

    case 'MOVE_RESOLVED': {
      const players = session.players.map((p) =>
        p.id === event.actorId ? { ...p, score: p.score + (event.points || 0) } : p
      );
      const completedMoves = session.completedMoves + 1;
      const limitReached = session.moveLimit != null && completedMoves >= session.moveLimit;
      const nextIndex = (session.activePlayerIndex + 1) % players.length;
      const status = limitReached ? STATUS.FINISHED : session.status;
      return {
        ...session,
        players,
        completedMoves,
        activePlayerIndex: status === STATUS.FINISHED ? session.activePlayerIndex : nextIndex,
        status,
        winnerIds: status === STATUS.FINISHED ? computeWinners({ ...session, players }) : [],
      };
    }

    case 'SET_LIMIT':
      return { ...session, moveLimit: event.moveLimit };

    case 'FINISH':
      return { ...session, status: STATUS.FINISHED, winnerIds: event.winnerIds };

    case 'RESET':
      return { ...session, players: session.players.map((p) => ({ ...p, score: 0 })), completedMoves: 0, activePlayerIndex: 0, status: STATUS.PLAYING, winnerIds: [] };

    default:
      return session;
  }
}
