"""Card-aware scoring for DevFun Arena TCG select options.

The arena observation does not expose an option ``damage`` field.  Options are
identified by ``type`` and, for attacks, ``attackId``.  This module scores the
real schema (``obs.current.players`` / ``obs.select.option``) and is shared by
the bot fallback path and the ISMCTS heuristic so both make the same decision.

Attack damage values are the ones published by the arena catalog for the cards
in the current deck.  Unknown attack ids score as neutral attacks rather than
crashing or silently becoming zero-value.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# Basic energy card ids in the arena catalog (Basic {G}/{R}/.../{M}).
BASIC_ENERGY_IDS = frozenset(range(1, 9))

# attackId -> printed damage, from /api/arena/tcg/attacks for the deck cards.
ATTACK_DAMAGE: Dict[int, int] = {
    901: 40,   # Druddigon - Shred
    902: 90,   # Druddigon - Ambush
    456: 30,   # Pikachu ex - Tail Whap
    457: 220,  # Pikachu ex - Thunder
    412: 30,   # Hop's Zacian ex - Insta-Strike
    413: 240,  # Hop's Zacian ex - Brave Slash
    31: 30,    # Enamorus - Heart Sign
    32: 80,    # Enamorus - Love Resonance
    545: 30,   # Tauros - Horn Attack
    546: 50,   # Tauros - Clean Hit
    323: 10,   # Budew - Itchy Pollen
    # S7 Audino / Alakazam / Dunsparce / Fezandipiti deck
    1070: 10,  # Abra - Teleportation Attack
    1071: 30,  # Kadabra - Super Psy Bolt
    338: 0,    # Alakazam - Strange Hacking (confuse/move damage)
    339: 10,   # Alakazam - Psychic (base; +50 per opponent energy)
    423: 0,    # Dunsparce - Trading Places (switch)
    424: 20,   # Dunsparce - Ram
    425: 0,    # Dudunsparce ex - Tenacious Tail (60 per opponent ex)
    426: 150,  # Dudunsparce ex - Destructive Drill
    183: 100,  # Fezandipiti ex - Cruel Arrow (bench snipe)
    791: 30,   # Audino - Return
    1453: 0,   # Mega Audino ex - Kaleidowaltz (energy acceleration)
    1454: 20,  # Mega Audino ex - Ear Force (base; +80 per opponent energy)
}

# hp for cards we can identify in our own deck/board.  Opponent board cards
# carry hp directly in obs, so no opponent catalog is needed.
CARD_HP: Dict[int, int] = {
    625: 120,
    328: 190,
    299: 230,
    39: 120,
    390: 130,
    235: 30,
    741: 50,
    742: 80,
    245: 140,
    305: 70,
    306: 270,
    140: 210,
    1006: 270,
    554: 100,
}

# Cards that count as Pokemon ex for effect damage. Mega ex counts as ex.
EX_CARD_IDS = {140, 306, 1006}

# Select option type codes observed in arena decision logs.
OPTION_CHOOSE_CARD = 3
OPTION_PLAY = 7
OPTION_ATTACH = 8
OPTION_EVOLVE = 9
OPTION_ABILITY = 10
OPTION_RETREAT = 12
OPTION_ATTACK = 13
OPTION_END_TURN = 14


def _energy_count(card: Any) -> int:
    if not isinstance(card, dict):
        return 0
    energies = card.get("energies")
    return len(energies) if isinstance(energies, list) else 0


def _opponent_ex_count(obs: Any) -> int:
    players = players_of(obs)
    oi = opponent_index(obs)
    if not 0 <= oi < len(players):
        return 0
    player = players[oi] or {}
    cards = list(player.get("active") or []) + list(player.get("bench") or [])
    count = 0
    for card in cards:
        if isinstance(card, dict) and card.get("id") in EX_CARD_IDS:
            count += 1
    return count


def real_damage(attack_id: int, obs: Any) -> int:
    """Return expected damage after the attack's printed effect scaling."""
    base = ATTACK_DAMAGE.get(attack_id, 0)
    target = opponent_active(obs)
    target_energy = _energy_count(target)
    if attack_id == 1454:  # Ear Force: 20 + 80 per energy on the opponent's Active
        return 20 + 80 * target_energy
    if attack_id == 339:  # Psychic: 10 + 50 per energy on the opponent's Active
        return 10 + 50 * target_energy
    if attack_id == 425:  # Tenacious Tail: 60 per opponent ex in play
        return 60 * _opponent_ex_count(obs)
    if attack_id == 183:  # Cruel Arrow: 100 to one chosen Pokemon
        return 100
    return base


def select_of(obs: Any) -> dict:
    """Return the select block for both known obs layouts."""
    if not isinstance(obs, dict):
        return {}
    current = obs.get("current")
    if isinstance(current, dict):
        select = current.get("select")
        if isinstance(select, dict):
            return select
    select = obs.get("select")
    return select if isinstance(select, dict) else {}


def players_of(obs: Any) -> List[dict]:
    if not isinstance(obs, dict):
        return []
    current = obs.get("current")
    if isinstance(current, dict):
        players = current.get("players")
        if isinstance(players, list):
            return players
    players = obs.get("players")
    return players if isinstance(players, list) else []


def your_index(obs: Any) -> int:
    if not isinstance(obs, dict):
        return 0
    current = obs.get("current")
    source = current if isinstance(current, dict) else obs
    try:
        return int(source.get("yourIndex", 0))
    except (TypeError, ValueError):
        return 0


def opponent_index(obs: Any) -> int:
    yi = your_index(obs)
    return 0 if yi == 1 else 1


def _active_of(obs: Any, player_index: int) -> Optional[dict]:
    players = players_of(obs)
    if not 0 <= player_index < len(players):
        return None
    active = players[player_index].get("active") or []
    for card in active:
        if isinstance(card, dict):
            return card
    return None


def our_active(obs: Any) -> Optional[dict]:
    return _active_of(obs, your_index(obs))


def opponent_active(obs: Any) -> Optional[dict]:
    return _active_of(obs, opponent_index(obs))


def parse_action_indices(action: Any) -> List[int]:
    """Parse legal action strings such as ``[0]`` or ``[0,2]``."""
    if not isinstance(action, str):
        return []
    text = action.strip()
    if text in ("", "[]"):
        return []
    if not (text.startswith("[") and text.endswith("]")):
        return []
    indices: List[int] = []
    for part in text[1:-1].split(","):
        part = part.strip()
        if not part:
            continue
        try:
            indices.append(int(part))
        except ValueError:
            return []
    return indices


def _card_id(card: Any) -> Optional[int]:
    if isinstance(card, dict):
        value = card.get("id", card.get("cardId"))
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if isinstance(card, int):
        return card
    return None


def _card_at(obs: Any, player_index: int, area: Any, index: Any) -> Optional[int]:
    """Resolve a select option to a card id when the referenced zone is visible."""
    card = _zone_card_at(obs, player_index, area, index)
    return _card_id(card) if card is not None else None


def _zone_card_at(obs: Any, player_index: int, area: Any, index: Any) -> Optional[dict]:
    """Resolve a select option to the visible card object, when one exists."""
    try:
        area = int(area)
        index = int(index)
    except (TypeError, ValueError):
        return None

    current = obs.get("current") if isinstance(obs, dict) else None
    if area == 7:
        stadium = (current or {}).get("stadium") or []
        if 0 <= index < len(stadium) and isinstance(stadium[index], dict):
            return stadium[index]
        return None

    players = players_of(obs)
    if not 0 <= player_index < len(players):
        return None
    player = players[player_index]

    zone_name = {
        1: "deck",      # hidden
        2: "hand",      # hidden in remote play
        3: "discard",
        4: "active",
        5: "bench",
        6: "prize",
    }.get(area)
    if zone_name is None:
        return None
    zone = player.get(zone_name)
    if not isinstance(zone, list) or not 0 <= index < len(zone):
        return None
    card = zone[index]
    return card if isinstance(card, dict) else None


def _option_card_id(option: dict, obs: Any) -> Optional[int]:
    direct = _card_id(option)
    if direct is not None:
        return direct
    player_index = option.get("playerIndex")
    try:
        player_index = int(player_index) if player_index is not None else your_index(obs)
    except (TypeError, ValueError):
        player_index = your_index(obs)
    return _card_at(obs, player_index, option.get("area"), option.get("index"))


def option_score(option: Any, obs: Any, belief: Any = None) -> float:
    """Score one select option using card/board semantics, not a fake damage field."""
    if not isinstance(option, dict):
        return 0.0
    option_type = option.get("type")

    if option_type == OPTION_ATTACK:
        try:
            attack_id = int(option.get("attackId") or 0)
        except (TypeError, ValueError):
            attack_id = 0
        damage = real_damage(attack_id, obs)
        score = 60.0 + damage * 1.5
        target = opponent_active(obs)
        if target is not None and damage:
            try:
                if damage >= int(target.get("hp", 0)):
                    score += 80.0  # takes the knockout
            except (TypeError, ValueError):
                pass
        return score

    if option_type == OPTION_PLAY:
        return 45.0
    if option_type == OPTION_ATTACH:
        return 25.0
    if option_type == OPTION_EVOLVE:
        return 80.0
    if option_type == OPTION_ABILITY:
        return 20.0
    if option_type == OPTION_RETREAT:
        score = -30.0
        active = our_active(obs)
        if isinstance(active, dict):
            try:
                hp = float(active.get("hp", 0))
                max_hp = float(active.get("maxHp", 0))
                if max_hp > 0 and hp / max_hp <= 0.35:
                    players = players_of(obs)
                    yi = your_index(obs)
                    bench = players[yi].get("bench") if 0 <= yi < len(players) else None
                    if isinstance(bench, list) and any(
                        isinstance(card, dict) and card.get("energies")
                        for card in bench
                    ):
                        score = 10.0
            except (TypeError, ValueError):
                pass
        if belief is not None:
            try:
                threats = belief.top_threats(3)
                if threats and threats[0][1] >= 0.6:
                    score += 10.0
            except Exception:
                pass
        return score
    if option_type == OPTION_END_TURN:
        return -25.0
    if option_type == OPTION_CHOOSE_CARD:
        score = 10.0
        card_id = _option_card_id(option, obs)
        player_index = option.get("playerIndex")
        try:
            player_index = int(player_index) if player_index is not None else your_index(obs)
        except (TypeError, ValueError):
            player_index = your_index(obs)
        card = _zone_card_at(obs, player_index, option.get("area"), option.get("index"))
        if card is not None:
            try:
                hp = float(card.get("hp") or card.get("maxHp") or 0)
                max_hp = float(card.get("maxHp") or hp)
                energies = len(card.get("energies") or [])
                score = 10.0 + hp / 10.0 + max_hp / 20.0 + energies * 8.0
            except (TypeError, ValueError):
                pass
        elif card_id in BASIC_ENERGY_IDS:
            score -= 5.0
        elif card_id in CARD_HP:
            score += CARD_HP[card_id] / 10.0
        return score
    # Setup choices (coin flip / first player) and unknown option types.
    return 10.0


def _energy_attached(obs: Any) -> bool:
    current = obs.get("current") if isinstance(obs, dict) else None
    if not isinstance(current, dict):
        return False
    return bool(current.get("energyAttached", False))


def best_attach_action(obs: Any, legal_actions: Sequence[str]) -> Optional[str]:
    """Choose the best energy-attach option, preferring the active Pokémon.

    Attaching does not end the turn, so when the turn's attachment is still
    available it must happen before an attack; the attack remains legal after.
    """
    options = select_of(obs).get("option") or []
    attach: List[tuple[float, str]] = []
    for action in legal_actions:
        indices = parse_action_indices(action)
        if len(indices) != 1:
            continue
        index = indices[0]
        if not 0 <= index < len(options):
            continue
        option = options[index]
        if not isinstance(option, dict) or option.get("type") != OPTION_ATTACH:
            continue

        score = 0.0
        target_area = option.get("inPlayArea")
        target_index = option.get("inPlayIndex")
        if target_area == 4:
            score += 100.0  # active Pokémon
        elif target_area == 5:
            score += 50.0   # bench
        card = _zone_card_at(obs, your_index(obs), target_area, target_index)
        if card is not None:
            try:
                score += float(card.get("maxHp") or card.get("hp") or 0) / 10.0
                score += len(card.get("energies") or []) * 8.0
            except (TypeError, ValueError):
                pass
        active = our_active(obs)
        try:
            active_max_hp = float(active.get("maxHp") or 0) if active else 0.0
        except (TypeError, ValueError):
            active_max_hp = 0.0
        if target_area == 5 and card is not None and active_max_hp and active_max_hp < 180:
            try:
                if float(card.get("maxHp") or 0) >= 180:
                    # Build a high-HP bench attacker while the fragile active
                    # is likely to be knocked out before it can use the energy.
                    score += 60.0
            except (TypeError, ValueError):
                pass
        attach.append((score, action))

    if not attach:
        return None
    attach.sort(key=lambda item: -item[0])
    return attach[0][1]


def _bench_empty(obs: Any) -> bool:
    """True when our side has no Benched Pokemon."""
    current = obs.get("current") or {}
    your_index = current.get("yourIndex", 0)
    players = current.get("players") or []
    if isinstance(your_index, int) and 0 <= your_index < len(players):
        player = players[your_index] or {}
        return not (player.get("bench") or [])
    return False


def _best_attack_damage(obs: Any, legal_actions: Sequence[str]) -> int:
    """Return the best printed damage among legal attack options."""
    options = select_of(obs).get("option") or []
    best = 0
    for action in legal_actions:
        indices = parse_action_indices(action)
        if len(indices) != 1:
            continue
        index = indices[0]
        if not 0 <= index < len(options):
            continue
        option = options[index]
        if not isinstance(option, dict) or option.get("type") != OPTION_ATTACK:
            continue
        try:
            attack_id = int(option.get("attackId") or 0)
        except (TypeError, ValueError):
            attack_id = 0
        best = max(best, real_damage(attack_id, obs))
    return best


def _in_play_value(obs: Any, option: dict) -> float:
    """Board value of the Pokemon an evolve option targets."""
    area = option.get("inPlayArea")
    index = option.get("inPlayIndex", 0)
    players = players_of(obs)
    yi = your_index(obs)
    if not 0 <= yi < len(players):
        return 0.0
    player = players[yi] or {}
    if area == 4:
        cards = player.get("active") or []
        bonus = 5.0
    elif area == 5:
        cards = player.get("bench") or []
        bonus = 0.0
    else:
        return 0.0
    try:
        card = cards[int(index)]
    except (IndexError, TypeError, ValueError):
        return 0.0
    if not isinstance(card, dict):
        return 0.0
    try:
        hp = float(card.get("hp", 0))
        max_hp = float(card.get("maxHp", 0))
    except (TypeError, ValueError):
        hp = max_hp = 0.0
    return bonus + hp / 10.0 + max_hp / 20.0 + _energy_count(card) * 5.0


def best_development_action(
    obs: Any, legal_actions: Sequence[str], allow_play: bool = True
) -> Optional[str]:
    """Return an evolution/ability/play action that does not end the turn.

    Attacking ends the turn, so evolve and ability options are always taken
    first. Trainer plays are taken first only when the best attack does zero
    printed damage; otherwise a damaging attack is still allowed.
    """
    options = select_of(obs).get("option") or []
    candidates: List[tuple[float, str]] = []
    for action in legal_actions:
        indices = parse_action_indices(action)
        if len(indices) != 1:
            continue
        index = indices[0]
        if not 0 <= index < len(options):
            continue
        option = options[index]
        if not isinstance(option, dict):
            continue
        option_type = option.get("type")
        if option_type == OPTION_EVOLVE:
            candidates.append((90.0 + _in_play_value(obs, option), action))
        elif option_type == OPTION_ABILITY:
            candidates.append((70.0, action))
        elif option_type == OPTION_PLAY and allow_play:
            candidates.append((50.0, action))
    if not candidates:
        return None
    candidates.sort(key=lambda item: -item[0])
    return candidates[0][1]


def action_score(action: Any, obs: Any, belief: Any = None) -> float:
    """Score a legal action string; multi-select actions sum their options."""
    indices = parse_action_indices(action)
    if not indices:
        return -25.0  # explicit pass / decline
    options = select_of(obs).get("option") or []
    total = 0.0
    for index in indices:
        if 0 <= index < len(options):
            total += option_score(options[index], obs, belief)
    total += 2.0 * len(indices)  # prefer completing a multi-card selection
    return total


def best_action(obs: Any, legal_actions: Sequence[str], belief: Any = None) -> Optional[str]:
    """Return the highest scoring legal action, preserving legal order on ties."""
    legal = [a for a in (legal_actions or []) if isinstance(a, str)]
    if not legal:
        return None
    if len(legal) == 1:
        return legal[0]
    # Attach first: it does not end the turn, and the attack remains available.
    if not _energy_attached(obs):
        attach = best_attach_action(obs, legal)
        if attach is not None:
            return attach
    # Developing the board must happen before an attack, because an attack
    # ends the turn. Trainer plays are forced when the bench is empty (a lone
    # Basic in hand is the only way to avoid no_active_pokemon) or when the
    # best attack does zero damage; otherwise a damaging attack is allowed so
    # the bot does not burn a Supporter blindly.
    bench_empty = _bench_empty(obs)
    attack_damage = _best_attack_damage(obs, legal)
    development = best_development_action(
        obs, legal, allow_play=bench_empty or attack_damage == 0
    )
    if development is not None:
        return development
    best = legal[0]
    best_score = action_score(best, obs, belief)
    for action in legal[1:]:
        score = action_score(action, obs, belief)
        if score > best_score:
            best, best_score = action, score
    return best
