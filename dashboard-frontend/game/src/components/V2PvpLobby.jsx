/**
 * V2PvpLobby — live presence lobby for direct, consent-based V2 matches.
 *
 * Guest-only adaptation for PanicRadar:
 *  - Every visitor receives a server-issued guest identity on connection.
 *  - No Google sign-in, auth module, config, or CSP references.
 *  - Lobby discloses that identities and PvP demo balances are temporary
 *    and reset on restart/reconnect.
 */
import React, { useEffect, useState } from 'react';

function statusLabel(status) {
  if (status === 'in_match') return 'In a match';
  if (status === 'challenging') return 'Challenge pending';
  return 'Available';
}

function shortId(userId) {
  return userId ? userId.slice(-6).toUpperCase() : '';
}

export default function V2PvpLobby({ session, connectionError, onRetry }) {
  const transport = session?.transport;
  const [lobby, setLobby] = useState(() => transport?.lastLobbySnapshot || null);
  const [incoming, setIncoming] = useState(null);
  const [outgoing, setOutgoing] = useState(null);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState(connectionError || '');

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (connectionError) setError(connectionError);
  }, [connectionError]);

  useEffect(() => {
    if (!transport) return undefined;

    return transport.onMessage((msg) => {
      if (msg.type === 'LOBBY_SNAPSHOT') {
        setLobby(msg);
      } else if (msg.type === 'MATCH_REQUEST_SENT') {
        setOutgoing({ requestId: msg.requestId, target: msg.target, expiresAt: msg.expiresAt });
        setNotice(`Challenge sent to ${msg.target.name}`);
        setError('');
      } else if (msg.type === 'MATCH_REQUEST_RECEIVED') {
        setIncoming({ requestId: msg.requestId, from: msg.from, expiresAt: msg.expiresAt });
        setNotice('Incoming challenge');
        setError('');
      } else if (['MATCH_REQUEST_CANCELLED', 'MATCH_REQUEST_DECLINED', 'MATCH_REQUEST_EXPIRED'].includes(msg.type)) {
        if (!msg.requestId || msg.requestId === incoming?.requestId) setIncoming(null);
        if (!msg.requestId || msg.requestId === outgoing?.requestId) setOutgoing(null);
        setNotice(msg.message || 'Challenge cleared');
      } else if (msg.type === 'ERROR') {
        setError(msg.message || 'Unable to update the lobby');
      } else if (msg.type === 'SYSTEM') {
        const text = msg.text || 'Disconnected from the lobby';
        if (text.startsWith('Reconnect')) {
          setNotice(text);
          if (text.startsWith('Reconnected')) setError('');
        } else {
          setError(text);
        }
      }
    });
  }, [transport, incoming?.requestId, outgoing?.requestId]);

  const identity = session?.identity || lobby?.self;
  const players = lobby?.players || [];
  const availableCount = players.filter((player) => player.status === 'available').length;

  const requestMatch = (targetUserId) => {
    setError('');
    transport.requestMatch(targetUserId);
  };

  const respond = (accept) => {
    if (!incoming) return;
    transport.respondToMatch(incoming.requestId, accept);
  };

  const cancel = () => {
    if (outgoing) transport.cancelMatch(outgoing.requestId);
  };

  if (!session) {
    return (
      <div className="pvp-lobby match-lobby match-lobby--opening" aria-live="polite">
        <p className="lobby-kicker">LIVE MATCH LOBBY</p>
        <h2 className="setup-title">Opening your table…</h2>
        <p className="lobby-blurb">Creating a private guest identity and finding active players.</p>
        {error && <div className="lobby-error">{error}</div>}
        {error && onRetry && (
          <button className="btn btn-primary" onClick={onRetry}>Try again</button>
        )}
      </div>
    );
  }

  return (
    <div className="pvp-lobby match-lobby">
      <div className="match-lobby-intro">
        <p className="lobby-kicker">LIVE MATCH LOBBY</p>
        <h2 className="setup-title">Find your next opponent</h2>
        <p className="lobby-blurb">
          Challenge any available player. A two-player demo-credit match begins only when they accept.
        </p>
        <p className="lobby-blurb" style={{ color: '#f4d03f', fontSize: '0.78rem', marginTop: 6 }}>
          Guest identities and PvP demo balances are temporary — they reset when the server restarts or you reconnect.
        </p>
      </div>

      <div className="lobby-identity">
        <div>
          <span className="identity-badge identity-badge--guest">
            Guest
          </span>
          <strong>{identity?.name}</strong>
          <span className="identity-id">ID {shortId(identity?.userId)}</span>
        </div>
      </div>

      {incoming && (
        <section className="challenge-card challenge-card--incoming" aria-live="assertive">
          <div>
            <span className="challenge-eyebrow">Incoming challenge</span>
            <strong>{incoming.from.name}</strong>
            <span>Guest player wants to play.</span>
          </div>
          <div className="challenge-actions">
            <button className="btn btn-primary" onClick={() => respond(true)}>Accept</button>
            <button className="btn" onClick={() => respond(false)}>Decline</button>
          </div>
        </section>
      )}

      {outgoing && (
        <section className="challenge-card challenge-card--outgoing" aria-live="polite">
          <div>
            <span className="challenge-eyebrow">Challenge sent</span>
            <strong>Waiting on {outgoing.target.name}</strong>
            <span>They can accept or decline from their lobby.</span>
          </div>
          <button className="btn btn-small" onClick={cancel}>Cancel</button>
        </section>
      )}

      <section className="presence-panel" aria-label="Online players">
        <header className="presence-head">
          <div>
            <span className="presence-overline">Players online</span>
            <strong>{players.length} at the table</strong>
          </div>
          <span className="presence-available">{availableCount} available</span>
        </header>

        <div className="presence-list">
          {players.map((player) => {
            const isSelf = player.userId === identity?.userId;
            const canChallenge = !isSelf && player.status === 'available' && !outgoing && !incoming;
            return (
              <div className={`presence-row presence-row--${player.status}`} key={player.userId}>
                <div className="presence-player">
                  <span className="presence-avatar presence-avatar--guest">
                    &#9679;
                  </span>
                  <div>
                    <strong>{isSelf ? `${player.name} (you)` : player.name}</strong>
                    <span>Guest &middot; {shortId(player.userId)}</span>
                  </div>
                </div>
                <div className="presence-action">
                  <span className={`presence-status presence-status--${player.status}`}>
                    {statusLabel(player.status)}
                  </span>
                  {!isSelf && (
                    <button className="btn btn-small" disabled={!canChallenge} onClick={() => requestMatch(player.userId)}>
                      Challenge
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <p className="wager-disclaimer">Demo credits only &middot; no real money &middot; game of skill</p>
      {notice && !error && <div className="lobby-status" aria-live="polite">{notice}</div>}
      {error && <div className="lobby-error" role="alert">{error}</div>}
    </div>
  );
}
