# ab_harness — offline ptcg-engine A/B scaffolding

P0/P1 only. Nothing here touches the live bot or opens a network connection.

## P0 — pinned engine

- Engine: `https://github.com/gemelom/ptcg-engine`, local checkout `~/ptcg-lab`
- Commit and dependency versions: `ENGINE.lock`
- Isolated venv: `~/ptcg-lab/.venv` (loguru, rich, pytest; engine installed editable)

```bash
~/ptcg-lab/.venv/bin/python -m ab_harness.smoke
```

Prints the imported engine commit, the `ptcg` import path, and the result of one
random-legal-action game between the engine's bundled `charizard_ex` and
`miraidon_ex` decks.

## P1 — deck conversion

`ab_harness/deck.py` holds the live 60-card list and the construction rules:

- exactly 60 cards
- at most 4 copies per name (Basic Energy exempt)
- at least one Basic Pokemon

`to_engine_lines()` / `write_engine_lines()` emit ptcg-engine's
`<count> <name> <set> <number>` format, but only from verified card references.

Known gap at the pinned commit: the engine implements none of the five arena
Pokemon (Druddigon 625, Pikachu ex 328, Hop's Zacian ex 299, Enamorus 39,
Tauros 390), so conversion raises `UnresolvedEngineCardError` rather than
inventing set numbers. Supply verified `EngineCard(name, set_code, number)`
entries through `card_map` once the cards exist or P2 chooses proxies.

## Tests

```bash
~/ptcg-lab/.venv/bin/python -m pytest -q tests/test_ab_deck.py tests/test_ab_engine_lock.py
```

The plain system interpreter has no `ptcg`, so engine-dependent tests skip
there; the bot's own suite stays green.
