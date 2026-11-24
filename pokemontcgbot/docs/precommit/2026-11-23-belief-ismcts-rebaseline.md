# VOID — 2026-11-24

This window was voided before its 900-match sample completed. The guardrail fix
for `l1-2026-11-24-guardrail-first` changes decisions inside the window; at void
time only 33 settled matches carried `l0-2026-11-23-belief-ismcts` (6 W, 27 L,
18.18%, Wilson lower bound 8.61%). No result from this window is valid. The
replacement boundary is `docs/precommit/2026-11-24-guardrail-first.md`.

# Precommit — belief ISMCTS rebasing boundary

Written before the new-policy process started. The numbers below are not chosen
after seeing a result. The prior 500-match window is void; see
`docs/precommit/2026-11-21-c-baseline-500.md`.

## Why

Commit `4caab8a` shipped a decision-affecting policy change inside the frozen
500-match window. That experiment cannot produce a clean before/after. This
precommit registers a new boundary for the already-shipped policy instead of
quoting a contaminated window.

## The window

- **Metric:** in-season win rate on `cmwm3cekx011nln01c3gqi0tc`, counted per
  settled match by `wr_report.py`.
- **Basis:** every settled match after the boundary below, no exclusions and no
  per-opponent filtering.
- **Boundary:** the first decision record in `~/.arena-tcg-decisions.jsonl`
  whose `policyVersion` is `l0-2026-11-23-belief-ismcts`. The corpus itself marks
  the start; no clock or commit hash is argued after the fact.
- **Sample:** 900 settled matches. Report nowhere earlier. A smaller window is
  a progress marker, not a result.
- **Bound:** G1 from the accepted plan — at least 47% point estimate with a
  Wilson 95% lower bound at least 43.5%, and rank 3 or better at sample close.
- **Freeze:** no policy or deck change ships inside this window. A change that
  alters decisions voids the window and requires a new precommit before restart.
- **Reversion:** if the lower bound at 900 is below 43.5%, revert to the last
  versioned policy that can be replayed and register a fresh boundary.

## Attribution contract

Every decision record in this window must carry
`policyVersion = l0-2026-11-23-belief-ismcts`. `telemetry.record()` resolves the
version at call time from `arena_config.POLICY_VERSION`, so a version bump is
visible without editing the call sites. Any record with a different version is
excluded from the A/B and reported as an attribution failure.

## Status

Registered 2026-11-23 before the process restart that activates
`l0-2026-11-23-belief-ismcts`. VOID 2026-11-24 by the guardrail change; do not
quote any result from this window.
