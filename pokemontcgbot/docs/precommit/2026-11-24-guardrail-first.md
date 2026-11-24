# Precommit — guardrail-first boundary

Registered before the 2026-11-24 restart. No number from this window has been
used to choose its threshold. The prior window is VOID; see
`docs/precommit/2026-11-23-belief-ismcts-rebaseline.md`.

## Defect being fixed

Replay of 394 decisions from recent prize-race losses found 120 disagreements
with the card-aware scorer. Across the full telemetry corpus, 599 decisions had
a mandatory attach or development option available; the belief path bypassed it
412 times (376 attach, 36 development). The belief scorer treated an attack as
immediately valuable and ended turns without the free attachment. Fix:
`scoring.mandatory_action()` runs before belief ISMCTS in `bot.py`.

## The window

- **Metric:** in-season win rate on `cmwm3cekx011nln01c3gqi0tc`, counted per
  settled match by `wr_report.py`.
- **Basis:** every settled match after the boundary below, no exclusions and no
  per-opponent filtering.
- **Boundary:** the first decision record in `~/.arena-tcg-decisions.jsonl`
  whose `policyVersion` is `l1-2026-11-24-guardrail-first`. The corpus marks the
  start; no clock or commit hash is argued after the fact.
- **Sample:** 500 settled matches. Report nowhere earlier; a smaller window is
  a progress marker, not a result.
- **Bound:** point estimate ≥ 46% with Wilson 95% lower bound ≥ 42%. This is G1
  from the world-class plan, chosen before the window opened.
- **Freeze:** no policy or deck change ships inside this window. A decision
  change voids it and requires a new precommit before restart.
- **Reversion:** if the 500-match lower bound is below 42%, revert the change
  and register a fresh boundary.

## Attribution contract

Every record in this window must carry
`policyVersion = l1-2026-11-24-guardrail-first`. `telemetry.record()` resolves
the version at call time from `arena_config.POLICY_VERSION`. A record with a
different version is excluded and reported as an attribution failure.

## Status

Registered 2026-11-24 before deployment. Result is `NOT_RUN` until 500 settled
matches exist.
