"""Belief-weighted ISMCTS consumes hidden-hand probabilities."""

from ismcts import ISMCTSSearch


class FakeBelief:
    def __init__(self, probs):
        self.probs = dict(probs)

    def hand_probabilities(self):
        return dict(self.probs)

    def top_threats(self, n=5, exclude_energy=True):
        return [(cid, p) for cid, p in self.probs.items() if p > 0][:n]

    def sync_from_obs(self, obs):
        return True


def _obs():
    return {
        "current": {
            "yourIndex": 0,
            "energyAttached": True,
            "players": [
                {
                    "active": [{"id": 305, "hp": 30, "maxHp": 100, "energies": [5, 5]}],
                    "bench": [{"id": 1006, "hp": 270, "maxHp": 270, "energies": [5, 5]}],
                },
                {
                    "active": [{"id": 140, "hp": 210, "maxHp": 210, "energies": []}],
                    "bench": [],
                },
            ],
            "select": {
                "type": 0,
                "option": [{"type": 13, "attackId": 1454}, {"type": 12}],
            },
        }
    }


LEGAL = ["[0]", "[1]"]


def test_without_belief_keeps_the_attack():
    search = ISMCTSSearch(FakeBelief({}), time_budget_ms=50, max_iterations=8, rng_seed=1)
    assert search.search(_obs(), LEGAL) == "[0]"


def test_gust_probability_changes_the_choice():
    search = ISMCTSSearch(
        FakeBelief({1182: 0.95}),
        time_budget_ms=50,
        max_iterations=8,
        rng_seed=1,
    )
    assert search.search(_obs(), LEGAL) == "[1]"


def test_search_is_deterministic_for_a_fixed_seed():
    def make():
        return ISMCTSSearch(
            FakeBelief({1182: 0.95}),
            time_budget_ms=50,
            max_iterations=8,
            rng_seed=7,
        )

    assert make().search(_obs(), LEGAL) == make().search(_obs(), LEGAL)


def test_chosen_action_is_always_legal():
    search = ISMCTSSearch(
        FakeBelief({1182: 0.5}),
        time_budget_ms=20,
        max_iterations=4,
        rng_seed=3,
    )
    assert search.search(_obs(), LEGAL) in LEGAL


def test_time_budget_is_bounded():
    import time

    search = ISMCTSSearch(
        FakeBelief({1182: 0.95}),
        time_budget_ms=25,
        max_iterations=1000,
        rng_seed=3,
    )
    started = time.monotonic()
    result = search.search(_obs(), LEGAL)
    assert result in LEGAL
    assert (time.monotonic() - started) < 0.5
