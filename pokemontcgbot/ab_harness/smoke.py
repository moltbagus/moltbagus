"""P0 smoke checks for the pinned local ptcg-engine.

Run with the engine venv:
    ~/ptcg-lab/.venv/bin/python -m ab_harness.smoke
"""

from __future__ import annotations

import json
import os
import random
import subprocess
from pathlib import Path

ENGINE_ROOT = Path(os.path.expanduser("~/ptcg-lab"))
ENGINE_SRC = ENGINE_ROOT / "src"


def engine_commit(engine_root: Path = ENGINE_ROOT) -> str:
    return subprocess.run(
        ["git", "-C", str(engine_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def smoke_import() -> dict:
    """Import the engine entry point and confirm it comes from the pinned tree."""
    from ptcg.core.envs import PokemonTCG
    import ptcg

    module_file = ptcg.__file__
    if module_file is None:
        raise RuntimeError("ptcg has no __file__; cannot verify the import source")
    module_path = Path(module_file).resolve()
    if ENGINE_SRC.resolve() not in module_path.parents:
        raise RuntimeError(f"ptcg imported from {module_path}, not {ENGINE_SRC}")

    return {
        "engine_commit": engine_commit(),
        "ptcg_module": str(module_path),
        "env_class": f"{PokemonTCG.__module__}.{PokemonTCG.__name__}",
    }


def smoke_game(seed: int = 7, max_steps: int = 2000) -> dict:
    """Play one random-legal-action game between two bundled engine decks."""
    from ptcg.core.envs import PokemonTCG

    env = PokemonTCG(seed=seed, deck1="charizard_ex", deck2="miraidon_ex", record_game=False)
    _, _, done, info = env.reset()
    rng = random.Random(seed)
    steps = 0

    while not done:
        actions = info.get("raw_available_actions") or []
        if not actions:
            raise RuntimeError(f"no legal actions at step {steps}")
        _, _, done, info = env.step(rng.choice(actions))
        steps += 1
        if steps >= max_steps:
            raise RuntimeError(f"game did not finish within {max_steps} steps")

    winner = info.get("winner")
    return {
        "seed": seed,
        "steps": steps,
        "winner": getattr(winner, "name", winner),
        "termination_reason": info.get("termination_reason"),
    }


def run_smoke() -> dict:
    return {"import": smoke_import(), "game": smoke_game()}


if __name__ == "__main__":
    print(json.dumps(run_smoke(), indent=2, sort_keys=True))
