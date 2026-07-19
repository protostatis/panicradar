# BlockCoined source and scope

The game engine, wagering reducer, controller, components, styles, and binary
assets (coin icons + score sound) are from
`protostatis/blockcoined2` commit `c3a9823`
(`V2: polish wagering flow and add river bonus swaps`).

## Integrated

- 8×8 tilted (diamond) match-3 board with five original coin-icon assets
- V2 street-based wagering: ante → flop/turn/river (1 move per player) →
  betting round (check/call/raise once/fold) → showdown → called-river bonus
  swaps
- Integrated HUD (pot / street / committed / phase / player stats / timer)
- Agent-turn overlay with spinner and status messaging
- Betting modal pop-up with countdown (auto-check-or-fold on timeout)
- Local persisted demo-coin balance, generated player name, and first-time
  tutorial swap hint
- Pixel-level gem animation (cascade slides, matched pops, gravity refill)
- Bundled score sound effect
- Original responsive/mobile scaling via CSS `transform: scale()`

## Excluded

The following portions of the upstream repository are intentionally NOT
included, as they are unreachable from the integrated V2 PvA (local) flow:

- Legacy self-play (1‑player endless) mode and game controller
- PvP WebSocket server and client transport
- Google OAuth authentication
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
- `App`: V2-only standalone shell with a PanicRadar back link; legacy modes
  remain excluded
- `Board`: keyboard navigation and ARIA labels without changing the tilted
  layout
- Dialog semantics and reduced-motion CSS were added without visual changes
- Components use JSX extensions for the Vite build

## License

See `LICENSE` in this directory (MIT — same as upstream).
