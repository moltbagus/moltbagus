"""P0 tests: the engine commit lock matches the installed engine and it runs."""

from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

import pytest

from ab_harness import smoke

pytest.importorskip("ptcg", reason="requires the pinned ~/ptcg-lab/.venv")

LOCK_PATH = Path(__file__).resolve().parent.parent / "ab_harness" / "ENGINE.lock"


@pytest.fixture(scope="module")
def lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def test_lock_pins_a_full_commit_and_install_command(lock):
    assert len(lock["commit"]) == 40
    int(lock["commit"], 16)
    assert lock["commit"] == smoke.engine_commit()
    assert "-e ~/ptcg-lab" in lock["install"]
    assert lock["dependencies"]["loguru"]
    assert lock["dependencies"]["rich"]


def test_locked_dependencies_are_the_installed_versions(lock):
    for name, expected in lock["dependencies"].items():
        assert importlib.metadata.version(name) == expected


def test_engine_import_comes_from_the_pinned_tree(lock):
    result = smoke.smoke_import()
    assert result["engine_commit"] == lock["commit"]
    assert result["ptcg_module"].startswith(str(Path(lock["local_path"]).expanduser()))
    assert result["env_class"] == "ptcg.core.envs.PokemonTCG"


def test_random_legal_action_game_finishes():
    result = smoke.smoke_game()
    assert result["steps"] > 0
    assert result["winner"] is not None
    assert result["termination_reason"]
