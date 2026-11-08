from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# Matches a plain integer followed by a unit letter, e.g. "25d", "3h", "2w".
# Used to parse optional duration arguments on /mut and /suspend.
_DURATION_RE = re.compile(r"^(\d+)\s*([dhwm])$", re.IGNORECASE)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def mute_until(days: int) -> datetime:
    return now_utc() + timedelta(days=days)


def parse_duration(text: str) -> timedelta | None:
    """Parses a short duration string like '25d', '3h', '2w' into a timedelta.

    Returns None if the text isn't a recognized duration (caller should treat
    that argument as something else, e.g. a username, instead).
    """
    match = _DURATION_RE.match(text.strip())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "d":
        return timedelta(days=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "w":
        return timedelta(weeks=value)
    if unit == "m":
        return timedelta(minutes=value)
    return None


def mute_until_delta(delta: timedelta) -> datetime:
    return now_utc() + delta


def fmt_user(telegram_id: int, username: str | None, full_name: str | None = None) -> str:
    """Returns a clickable mention using tg://user for reliability even
    when the user has no @username set."""
    label = f"@{username}" if username else (full_name or str(telegram_id))
    return f'<a href="tg://user?id={telegram_id}">{label}</a>'
