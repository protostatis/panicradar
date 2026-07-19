/**
 * MatchLobby.js — online presence and consent-based V2 matchmaking.
 *
 * The lobby owns only public availability and challenge requests. The match
 * itself remains an authoritative V2WagerRoom created after both players agree.
 *
 * Guest-only adaptation: Google sign-in references removed.
 */
import { randomBytes } from 'crypto';

const DEFAULT_REQUEST_TTL_MS = 30_000;
const DEFAULT_MAX_PENDING_REQUESTS = 100;

export class MatchLobby {
  constructor({
    send,
    onMatchAccepted,
    requestTtlMs = DEFAULT_REQUEST_TTL_MS,
    maxPendingRequests = DEFAULT_MAX_PENDING_REQUESTS,
  }) {
    this.send = send;
    this.onMatchAccepted = onMatchAccepted;
    this.requestTtlMs = requestTtlMs;
    this.maxPendingRequests = maxPendingRequests;
    this.players = new Map();
    this.requests = new Map();
    this.requestByPlayer = new Map();
  }

  _publicPlayer(record) {
    return {
      userId: record.player.id,
      name: record.player.name,
      authType: record.player.authType,
      status: record.inMatch
        ? 'in_match'
        : this.requestByPlayer.has(record.player.id)
          ? 'challenging'
          : 'available',
    };
  }

  _playerList() {
    return [...this.players.values()]
      .map((record) => this._publicPlayer(record))
      .sort((a, b) => a.name.localeCompare(b.name) || a.userId.localeCompare(b.userId));
  }

  _sendTo(userId, message) {
    const record = this.players.get(userId);
    if (!record) return;
    for (const ws of record.sockets) this.send(ws, message);
  }

  _broadcast() {
    const players = this._playerList();
    for (const record of this.players.values()) {
      for (const ws of record.sockets) {
        this.send(ws, {
          type: 'LOBBY_SNAPSHOT',
          self: this._publicPlayer(record),
          players,
        });
      }
    }
  }

  _newRequestId() {
    return `request_${randomBytes(12).toString('base64url')}`;
  }

  _clearRequest(request) {
    clearTimeout(request.timer);
    this.requests.delete(request.requestId);
    this.requestByPlayer.delete(request.fromUserId);
    this.requestByPlayer.delete(request.targetUserId);
  }

  _cancelRequestFor(userId, reason) {
    const requestId = this.requestByPlayer.get(userId);
    if (!requestId) return false;

    const request = this.requests.get(requestId);
    if (!request) {
      this.requestByPlayer.delete(userId);
      return false;
    }

    this._clearRequest(request);
    this._sendTo(request.fromUserId, {
      type: 'MATCH_REQUEST_CANCELLED',
      requestId: request.requestId,
      message: reason,
    });
    this._sendTo(request.targetUserId, {
      type: 'MATCH_REQUEST_CANCELLED',
      requestId: request.requestId,
      message: reason,
    });
    return true;
  }

  _available(record) {
    return Boolean(record) && !record.inMatch && !this.requestByPlayer.has(record.player.id);
  }

  attach(ws, player) {
    let record = this.players.get(player.id);
    if (!record) {
      record = { player, sockets: new Set(), inMatch: false };
      this.players.set(player.id, record);
    } else {
      record.player = player;
    }
    record.sockets.add(ws);
    this._broadcast();
  }

  detach(ws, userId) {
    const record = this.players.get(userId);
    if (!record) return;

    record.sockets.delete(ws);
    if (record.sockets.size === 0) {
      this._cancelRequestFor(userId, `${record.player.name} left the lobby`);
      this.players.delete(userId);
    }
    this._broadcast();
  }

  request(fromUserId, targetUserId) {
    if (fromUserId === targetUserId) return { ok: false, error: 'You cannot challenge yourself' };
    if (this.requests.size >= this.maxPendingRequests) {
      return { ok: false, error: 'The challenge queue is full — try again shortly' };
    }

    const from = this.players.get(fromUserId);
    const target = this.players.get(targetUserId);
    if (!this._available(from)) return { ok: false, error: 'You are not available to challenge a player' };
    if (!this._available(target)) return { ok: false, error: 'That player is not available' };

    const requestId = this._newRequestId();
    const expiresAt = Date.now() + this.requestTtlMs;
    const request = {
      requestId,
      fromUserId,
      targetUserId,
      expiresAt,
      timer: null,
    };
    request.timer = setTimeout(() => {
      if (!this.requests.has(requestId)) return;
      this._clearRequest(request);
      this._sendTo(fromUserId, {
        type: 'MATCH_REQUEST_EXPIRED',
        requestId,
        message: 'Challenge expired',
      });
      this._sendTo(targetUserId, {
        type: 'MATCH_REQUEST_EXPIRED',
        requestId,
        message: 'Challenge expired',
      });
      this._broadcast();
    }, this.requestTtlMs);
    request.timer.unref?.();

    this.requests.set(requestId, request);
    this.requestByPlayer.set(fromUserId, requestId);
    this.requestByPlayer.set(targetUserId, requestId);

    this._sendTo(fromUserId, {
      type: 'MATCH_REQUEST_SENT',
      requestId,
      target: this._publicPlayer(target),
      expiresAt,
    });
    this._sendTo(targetUserId, {
      type: 'MATCH_REQUEST_RECEIVED',
      requestId,
      from: this._publicPlayer(from),
      expiresAt,
    });
    this._broadcast();
    return { ok: true, requestId, expiresAt };
  }

  respond(targetUserId, requestId, accept) {
    const request = this.requests.get(requestId);
    if (!request || request.targetUserId !== targetUserId) {
      return { ok: false, error: 'Challenge request not found' };
    }

    const from = this.players.get(request.fromUserId);
    const target = this.players.get(targetUserId);
    if (!from || !target || from.sockets.size === 0 || target.sockets.size === 0) {
      this._clearRequest(request);
      this._broadcast();
      return { ok: false, error: 'That player is no longer online' };
    }

    if (!accept) {
      this._clearRequest(request);
      this._sendTo(request.fromUserId, {
        type: 'MATCH_REQUEST_DECLINED',
        requestId,
        message: `${target.player.name} declined the challenge`,
      });
      this._sendTo(targetUserId, {
        type: 'MATCH_REQUEST_DECLINED',
        requestId,
        message: 'Challenge declined',
      });
      this._broadcast();
      return { ok: true };
    }

    let match;
    try {
      match = this.onMatchAccepted({ from: from.player, target: target.player });
    } catch (error) {
      match = { ok: false, error: error.message || 'Unable to start the match' };
    }
    if (!match?.ok) {
      this._clearRequest(request);
      this._sendTo(request.fromUserId, {
        type: 'MATCH_REQUEST_CANCELLED',
        requestId,
        message: match?.error || 'Unable to start the match',
      });
      this._sendTo(targetUserId, {
        type: 'MATCH_REQUEST_CANCELLED',
        requestId,
        message: match?.error || 'Unable to start the match',
      });
      this._broadcast();
      return { ok: false, error: match?.error || 'Unable to start the match' };
    }

    this._clearRequest(request);
    from.inMatch = true;
    target.inMatch = true;
    this._sendTo(request.fromUserId, { type: 'MATCH_STARTED' });
    this._sendTo(targetUserId, { type: 'MATCH_STARTED' });
    this._broadcast();
    return { ok: true };
  }

  cancel(fromUserId, requestId) {
    const request = this.requests.get(requestId);
    if (!request || request.fromUserId !== fromUserId) {
      return { ok: false, error: 'Challenge request not found' };
    }
    this._clearRequest(request);
    this._sendTo(request.fromUserId, {
      type: 'MATCH_REQUEST_CANCELLED',
      requestId,
      message: 'Challenge cancelled',
    });
    this._sendTo(request.targetUserId, {
      type: 'MATCH_REQUEST_CANCELLED',
      requestId,
      message: 'Challenge cancelled',
    });
    this._broadcast();
    return { ok: true };
  }

  endMatch(userIds, message = 'Match ended') {
    for (const userId of userIds) {
      const record = this.players.get(userId);
      if (record) record.inMatch = false;
    }
    for (const userId of userIds) {
      this._sendTo(userId, { type: 'MATCH_ENDED', message });
    }
    this._broadcast();
  }
}

export default MatchLobby;
