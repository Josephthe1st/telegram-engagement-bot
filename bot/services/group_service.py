from __future__ import annotations

from pathlib import Path

from bot.database import queries as q
from bot.database.db import Database

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_RULES_1 = (DATA_DIR / "rules_default_1.txt").read_text(encoding="utf-8")
DEFAULT_RULES_2 = (DATA_DIR / "rules_default_2.txt").read_text(encoding="utf-8")
DEFAULT_RULES_3 = "This is Rule 3"


async def ensure_group(db: Database, group_id: int, title: str | None) -> None:
    await q.upsert_group(db, group_id, title)


async def enable_tracking(db: Database, group_id: int) -> None:
    await q.set_tracking(db, group_id, True)


async def is_tracking_enabled(db: Database, group_id: int) -> bool:
    group = await q.get_group(db, group_id)
    return bool(group and group["tracking_enabled"])


def _default_rules(slot: int) -> str:
    if slot == 1:
        return DEFAULT_RULES_1
    if slot == 2:
        return DEFAULT_RULES_2
    return DEFAULT_RULES_3


async def get_rules(db: Database, group_id: int, slot: int) -> str:
    group = await q.get_group(db, group_id)
    if group is None:
        return _default_rules(slot)
    column = {1: "rules1", 2: "rules2", 3: "rules3"}[slot]
    text = group[column]
    if text:
        return text
    return _default_rules(slot)


async def set_rules(db: Database, group_id: int, slot: int, text: str) -> None:
    await q.set_group_rules(db, group_id, slot, text)
