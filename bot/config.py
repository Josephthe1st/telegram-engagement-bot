from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# bot/config.py -> project root is one level up from the bot/ package.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env explicitly from the project root, regardless of the directory
# the bot happens to be launched from (so `python run.py` works the same
# whether you run it from the project folder or anywhere else).
load_dotenv(dotenv_path=BASE_DIR / ".env")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            continue
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "data/bot.sqlite3"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # Global allowlist of Telegram user IDs allowed to run admin commands,
    # across every connected group. Empty -> falls back to each group's own
    # Telegram admin/creator status.
    admin_ids: frozenset[int] = field(
        default_factory=lambda: _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
    )

    link_reminder_interval_min: int = field(
        default_factory=lambda: _int_env("LINK_REMINDER_INTERVAL_MIN", 15)
    )
    scam_reminder_interval_min: int = field(
        default_factory=lambda: _int_env("SCAM_REMINDER_INTERVAL_MIN", 20)
    )
    deletion_check_interval_min: int = field(
        default_factory=lambda: _int_env("DELETION_CHECK_INTERVAL_MIN", 5)
    )

    fraud_mute_days: int = field(default_factory=lambda: _int_env("FRAUD_MUTE_DAYS", 18))
    suspend_mute_days: int = field(default_factory=lambda: _int_env("SUSPEND_MUTE_DAYS", 16))

    def resolved_db_path(self) -> Path:
        p = Path(self.db_path)
        if not p.is_absolute():
            p = BASE_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
