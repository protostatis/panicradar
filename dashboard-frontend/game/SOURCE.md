# BlockCoined source and scope

The game engine, wagering reducer, controller, components, styles, and binary
assets (coin icons + score sound) are synchronized from
`protostatis/blockcoined2` through commit `e6c98a7`
(`fix: restore V2 PvP cascade effects`), based on the PvP merge at `54862d5`.

## Integrated

- 8×8 tilted (diamond) match-3 board with five original coin-icon assets
- V2 street-based wagering: ante → flop/turn/river (1 move per player) →
  betting round (check/call/raise once/fold) → showdown → called-river bonus
  swaps
- Integrated HUD (pot / street / committed / phase / player stats / timer)
- Agent-turn overlay with spinner and status messaging
- Betting modal pop-up with countdown (auto-check-or-fold on timeout)
- Local persisted demo-coin balance, generated player name, and first-time
  tutorial swap hint (PvA mode only)
- Pixel-level gem animation (cascade slides, matched pops, gravity refill)
- Bundled score sound effect
- Original responsive/mobile scaling via CSS `transform: scale()`
- V2 PvP lobby with guest identities, public presence, consent-based
  challenges, and server-authoritative V2WagerRoom match flow
- Server-authored cascade traces for presentation-only PvP board animation
- Rematch consensus flow with both-players-must-agree semantics

## Excluded

The following portions of the upstream repository are intentionally NOT
included, as they are either unreachable or out of scope:

- Legacy self-play (1‑player endless) mode and game controller
- Legacy V1 PvP WebSocket server and client transport (Room.js, pvpTransport.js)
- Google OAuth authentication (googleAuth.js)
- EOS smart contracts
- OpenRouter user-facing setup (agent always uses no‑key deterministic
  fallback; the client module is retained so local behavior is unchanged)

## Adaptations

- `GameEngine`: accepts an optional seeded random-number generator for
  deterministic testing (default: `Math.random`)
- `wagering.js`: syncs match scores into seat objects during
  `recordStreetMove` so the pure reducer can settle pots in tests without the
  controller; rejects antes when any seat is under the minimum
- `sound.js`: Vite asset import (mp3) replaces CRA file-loader
- `App`: V2 PvA + PvP standalone shell with a PanicRadar back link; legacy
  modes remain excluded; landing offers Play vs AI and Play with a friend
- `Board`: keyboard navigation and ARIA labels without changing the tilted
  layout
- Dialog semantics and reduced-motion CSS were added without visual changes
- Components use JSX extensions for the Vite build
- `V2PvpLobby`: guest-only; no Google sign-in; discloses temporary
  identity/balance reset behaviour
- `V2PvpScreen`: guest-only; reuses Board; server-authoritative snapshots
- `usePvpWagerController`: client-side swap validation and presentation-only
  cascade animation; all wagering mutations remain server commands
- `v2PvpTransport`: derives ws/wss from location.host (/game/ws); permits
  VITE_PVP_URL override for local dev; versioned protocol handshake
  (protocolVersion 1); no Google auth integration
- `server/`: production-hardened V2-only WebSocket server with HTTP health
  check, strict origin allowlist, per-IP/per-socket rate limits, heartbeat,
  graceful shutdown, dead-board reshuffle, and deadline/disconnect
  forfeit/settlement policies

## License

See `LICENSE` in this directory (MIT — same as upstream).
