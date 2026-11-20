"""Deployment scripts must not carry a second copy of the season identity.

The restart gate once held the previous season's competition id, so it read
"0 active matches" while the live season still had one and restarted the bot
mid-match. These tests keep that from coming back, and keep the live-sync list
in step with the modules the bot actually imports.
"""

import subprocess
from pathlib import Path

import arena_config

ROOT = Path(__file__).resolve().parent.parent
RESTART = "restart_when_idle.sh"
SYNC = ".agent-team/sync-live.sh"
# The S6 competition id; the exact literal that caused the mid-match restart.
S6_COMPETITION_ID = "cmw99opb57gssgfb7rj39a1o1"


def _read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_restart_script_reads_the_season_from_arena_config():
    source = _read(RESTART)
    assert "import arena_config" in source
    assert "COMPETITION_ID" in source
    assert arena_config.COMPETITION_ID not in source, "competition id must not be hardcoded"
    assert S6_COMPETITION_ID not in source, "stale season id, restarts mid-match"
    assert "arena.dev.fun" not in source, "base URL must come from arena_config"


def test_restart_script_gates_on_active_matches():
    source = _read(RESTART)
    assert "activeMatches" in source
    assert "--user restart tcg-bot.service" in source


def test_restart_script_is_executable():
    assert (ROOT / RESTART).stat().st_mode & 0o111


def test_sync_live_deploys_every_module():
    source = _read(SYNC)
    for module in (
        "arena_config.py",
        "telemetry.py",
        "bot.py",
        "bot_async.py",
        "scoring.py",
        "wr_report.py",
    ):
        assert module in source, f"sync-live.sh would not deploy {module}"


def test_shell_scripts_parse():
    for name in (RESTART, SYNC):
        result = subprocess.run(
            ["bash", "-n", str(ROOT / name)], capture_output=True, text=True
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"
