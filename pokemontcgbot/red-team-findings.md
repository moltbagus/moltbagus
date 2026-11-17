# Red-Team Findings — PTCG Bot Heuristic (2026-11-17)

## Reviewed Files
- `bot/client.py` (HeuristicPolicy class)
- `self_play.py` (HeuristicPolicy class)

## Findings

### 1. CRITICAL: `me.get("bench")` may be None, not []
**File:** bot/client.py, line ~120
**Issue:** `bench = me.get("bench") or []` handles None but if bench is a list of dicts, `len(bench)` works. However, if `me` is None (obs missing), `me.get()` throws AttributeError before the `or []` fallback.
**Fix:** `me = (state.get("me") or {})` already guards this, but `state` itself could be None. Add: `state = req.get("state") or {}`.

### 2. CRITICAL: state access in self_play uses `info.get("full_state")` which may not exist
**File:** self_play.py, line ~59
**Issue:** `state = info.get("full_state")` — but `expose_full_state` must be True when creating the env. If False, `full_state` is not in info, and `state.player1` throws AttributeError.
**Fix:** Guard with `state = info.get("full_state")` and check `if state is not None` before accessing `.player1`.

### 3. BUG: `_rank()` function crashes on None card
**File:** bot/client.py
**Issue:** `_rank(card: str | None)` handles None by returning 500, but `slug_of(a)` can return None, and `_rank(None)` is called in `search = sorted([a for a in plays if _rank(slug_of(a)) < 60], ...)`. If slug_of returns None, `_rank(None)` returns 500, which is >= 60, so it's filtered out. This is actually correct behavior but the type annotation says `str | None` which is fine.

### 4. BUG: `hand.get(a.get("entity_id"))` — entity_id may not be in hand
**File:** bot/client.py
**Issue:** In the arena protocol, `legal_actions` contain `entity_id` references to hand cards. But `hand` is built from `me.get("hand")` which may not include all cards if the obs is stale. If `hand.get(entity_id)` returns None, `slug_of` returns None, and the action is misclassified.
**Fix:** Add fallback: if slug is None, try to look up from a card ID map.

### 5. MISSING: No handling for `choose_yes_no`, `choose_one_branch`, `distribute_damage` prompts
**File:** bot/client.py, choose_prompt method
**Issue:** The heuristic's `choose_prompt` only handles `choose_yes_no`, `choose_first_or_second`, and `choose_from_zone`/`reorder_cards`. For all other 17 prompt kinds, it falls back to `random_choice`, which may pick suboptimal options.
**Impact:** Suboptimal card selection during search, discard, damage distribution, etc.

### 6. PERFORMANCE: `slug_of` called multiple times per action
**File:** bot/client.py
**Issue:** `slug_of(a)` is called in multiple list comprehensions (dev, search, energies, others). Each call does a dict lookup. For large action lists this is O(n) per comprehension, O(n²) total.
**Fix:** Pre-compute a dict mapping action -> slug once.

### 7. MISSING: No prize-value targeting
**File:** bot/client.py
**Issue:** Attacks are scored by damage + KO bonus + ex bonus, but the ex bonus is a flat 500. Should be: ex = 2 prizes = 2x value. Also missing: prize race awareness (how many prizes each side has left).
**Fix:** Score attacks by: damage + (1000 if KO) + (500 if ex target) + (prize_differential * 200).

### 8. MISSING: No energy accounting
**File:** bot/client.py
**Issue:** Energy attachment happens whenever `energy_attached_this_turn` is False, but doesn't check if the active Pokemon needs energy for its attack. Could attach energy to a Pokemon that can't attack.
**Fix:** Only attach energy if active's attack cost > current energy count.

### 9. EDGE CASE: `attacks[-1]` assumes last attack is strongest
**File:** bot/client.py
**Issue:** `sorted(attacks, key=lambda a: a.get("attack_index", 0))[-1]` picks the last attack by index, not by damage. Attack index 0 might do 100 damage while index 1 does 10.
**Fix:** Sort by damage, not attack_index.

### 10. MISSING: No retreat logic in heuristic
**File:** bot/client.py
**Issue:** The heuristic has no retreat handling. When active is low HP, it should retreat to a bench Pokemon. Currently retreats are only considered as a fallback.
**Fix:** Add retreat scoring: if active HP < 40% and bench has healthy Pokemon, prefer retreat.

### 11. STATE ACCESS: `a.get("entity_id")` may not exist on all actions
**File:** bot/client.py
**Issue:** Some action types (like end_turn, use_ability) may not have entity_id. The `a.get()` call assumes dict-like access. If actions are objects (as in ptcg-engine), this fails.
**Note:** The arena protocol uses dicts, so this is fine for arena. But self_play.py uses Action objects, so the heuristic there needs different access patterns.

### 12. PERFORMANCE: No caching of opponent threat assessment
**File:** bot/client.py
**Issue:** Belief tracker's top_threats() is called on every action selection, recomputing hand probabilities each time. For 4 legal actions, that's 4 probability computations.
**Fix:** Compute threats once per decision point, cache in entry.

## Summary of Critical Issues
1. State access errors in self_play (full_state may be None)
2. Missing prompt handlers (17 of 21 prompt kinds use random fallback)
3. No prize-value targeting (ex KOs not prioritized)
4. No energy accounting (energy attached blindly)
5. Attack selection by index, not damage
6. No retreat logic

## Recommended Priority
1. Fix state access in self_play (prevents crashes)
2. Add prize-value targeting (biggest WR improvement)
3. Add energy accounting (prevents wasted energy)
4. Fix attack selection (sort by damage)
5. Add retreat logic
6. Handle more prompt kinds