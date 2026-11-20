"""Suite-wide isolation from live production state.

Several tests exercise ``bot.choose_action`` with synthetic decisions. Without
this fixture they append those synthetic decisions to the live telemetry log
(``~/.arena-tcg-decisions.jsonl``), which pollutes the corpus the offline
replay gate is supposed to trust.
"""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_telemetry(tmp_path_factory):
    target = tmp_path_factory.mktemp("telemetry") / "decisions.jsonl"
    previous = os.environ.get("ARENA_TELEMETRY_PATH")
    os.environ["ARENA_TELEMETRY_PATH"] = str(target)
    try:
        yield target
    finally:
        if previous is None:
            os.environ.pop("ARENA_TELEMETRY_PATH", None)
        else:
            os.environ["ARENA_TELEMETRY_PATH"] = previous
