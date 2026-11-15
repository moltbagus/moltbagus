# Deterministic Checks — Lauren Tan Principle Applied to Pokemon TCG Bot

## Source
Lauren Tan (SpaceX/xAI desktop client team) — AI Engineer Code Summit talk.
Thesis: The meta-skill is no longer writing code — it's maintaining code quality while raising throughput.
Trust comes from investing in the agent's environment, not better prompts.

## Priority Pyramid (inverted)
1. **Deterministic code constraints** — architecture, API design, refactoring, lint rules, type systems, compilers, tests
2. **Verification** — runtime, then formal
3. **Prose** — rules, skills, AGENTS.md — last, and as little as possible

## Core Principle
> Every time you correct your agent, turn it into a deterministic check — not another line in AGENTS.md.
> Because prose isn't enforceable, and agents treat it as an escape hatch.

## Applied to Pokemon TCG Bot

### 1. Deck Viability Check (replaces "Budew is too weak" note)
**Problem:** Budew (30 HP, 10 damage) lost all 5 matches — knocked out in 1 hit.
**Old approach:** Memory note saying "Budew deck too weak."
**New approach:** `test_deck_viability.py` — asserts every Basic Pokémon has ≥ 80 HP and ≥ 30 damage. CI fails if violated.

```python
# test_deck_viability.py
def test_basic_pokemon_hp():
    for card_id, count in deck_items:
        if card_id in BASIC_POKEMON:
            assert hp(card_id) >= 80, f"Card {card_id} has {hp(card_id)} HP < 80"

def test_basic_pokemon_damage():
    for card_id, count in deck_items:
        if card_id in BASIC_POKEMON:
            assert max_damage(card_id) >= 30, f"Card {card_id} max damage < 30"
```

### 2. Decision Latency Check (replaces "timeout forfeit" note)
**Problem:** 34% of losses are "timeout_forfeit" — decision loop too slow.
**Old approach:** Memory note saying "bot is too slow."
**New approach:** `test_decision_latency.py` — measures choose_action() execution time, fails if > 1.5s.

```python
# test_decision_latency.py
def test_choose_action_latency():
    start = time.monotonic()
    action = choose_action(entry, belief_heuristic)
    elapsed = time.monotonic() - start
    assert elapsed < 1.5, f"Decision took {elapsed:.2f}s > 1.5s limit"
```

### 3. No-Active-Pokemon Prevention (replaces match analysis note)
**Problem:** 66% of losses = "no_active_pokemon" — all Pokémon knocked out.
**Old approach:** Obsidian note analyzing match replays.
**New approach:** `test_bench_depth.py` — asserts deck has ≥ 4 distinct Basic Pokémon (bench depth). Also asserts total HP of all Basics ≥ 600.

```python
# test_bench_depth.py
def test_bench_depth():
    basics = [c for c in DECK if c in BASIC_POKEMON]
    distinct = len(set(basics))
    assert distinct >= 4, f"Only {distinct} distinct Basics, need ≥ 4"
    total_hp = sum(hp(c) for c in basics)
    assert total_hp >= 600, f"Total Basic HP {total_hp} < 600"
```

### 4. Secret Exposure Prevention (from poker bot lesson)
**Problem:** API keys found in plaintext in .hermes_history and .bash_history.
**Old approach:** Memory note saying "don't cat .env in TUI."
**New approach:** Pre-commit hook that scans staged files for secret patterns.

```bash
# .git/hooks/pre-commit
#!/bin/bash
if git diff --cached --name-only | xargs grep -l "arena_sk_\|api_key.*=.*[a-zA-Z0-9]\{20,\}" 2>/dev/null; then
    echo "ERROR: Possible secret detected in staged files"
    exit 1
fi
```

### 5. Deck Lock Safety (from arena skill pitfall)
**Problem:** Remote-mode deck is locked on first join — smoke test join is irreversible.
**Old approach:** Prose warning in SKILL.md.
**New approach:** `test_join_safety.py` — asserts `--join-only` flag is required for first join, and warns if deck hasn't been validated.

### Priority Order for Pokemon Bot
1. Deck viability tests (deterministic) — DONE as spec, need test files
2. Latency tests (deterministic) — need implementation
3. Bench depth tests (deterministic) — need implementation
4. Secret scanning hook (deterministic) — need implementation
5. Memory notes (prose) — keep as reference only, not enforcement

### Concrete Moves to Make
- [ ] Create `tests/test_deck_viability.py`
- [ ] Create `tests/test_decision_latency.py`
- [ ] Create `tests/test_bench_depth.py`
- [ ] Create `.git/hooks/pre-commit` for secret scanning
- [ ] Delete memory notes that are now covered by tests
- [ ] Keep AGENTS.md minimal — only non-enforceable guidance