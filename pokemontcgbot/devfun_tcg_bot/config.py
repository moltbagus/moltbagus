from dataclasses import dataclass
import os


@dataclass(frozen=True)
class BotConfig:
    arena_base_url: str = os.getenv("DEVFUN_ARENA_URL", "https://arena.dev.fun")
    skills_manifest_url: str = "https://arena.dev.fun/skills/arena.md"
    api_key: str = os.getenv("DEVFUN_API_KEY", "")
    agent_id: str = os.getenv("DEVFUN_AGENT_ID", "tcg-champion-v3")
    db_path: str = os.getenv("DEVFUN_DB_PATH", "tcg_telemetry.sqlite")

    expectimax_budget_ms: int = 240
    hard_turn_timeout_sec: float = 1.40

    stakes_entry_fee: float = 0.10
    min_playground_matches: int = 100
    min_playground_winrate: float = 0.62
    min_stakes_bankroll: float = 5.00
    stakes_rolling_window: int = 30
    stakes_stop_loss_winrate: float = 0.54

    season_lock_hours: float = 6.0
    min_rating_cushion: float = 35.0
    softmax_temperature: float = 0.15


CONFIG = BotConfig()
