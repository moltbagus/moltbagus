# Offline-only reference files

These are the deployment files from the v2 specification. They are kept here
for reference and are **not deployable against arena.dev.fun**: `runner.py`,
`telemetry.py`, and `bankroll.py` from that package do not exist in this repo,
and the runner targets endpoints/auth that the live arena does not expose.

The live bot remains `bot_async.py` in the live working directory under pm2. Nothing in
this directory is imported by it.

See `arena_adapter.py` for the verified mapping to the real introspection schema.
