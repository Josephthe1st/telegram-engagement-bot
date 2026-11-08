from __future__ import annotations

from typing import Any, Optional

from aiosqlite import Row

from bot.database.db import Database

# ---------------------------------------------------------------------------
# groups
# ---------------------------------------------------------------------------

async def upsert_group(db: Database, group_id: int, title: str | None) -> None:
    await db.execute(
        """
        INSERT INTO groups (group_id, title) VALUES (?, ?)
        ON CONFLICT(group_id) DO UPDATE SET title = excluded.title
        """,
        (group_id, title),
    )


async def get_group(db: Database, group_id: int) -> Optional[Row]:
    return await db.fetchone("SELECT * FROM groups WHERE group_id = ?", (group_id,))


async def set_tracking(db: Database, group_id: int, enabled: bool) -> None:
    await db.execute(
        "UPDATE groups SET tracking_enabled = ? WHERE group_id = ?",
        (1 if enabled else 0, group_id),
    )


async def set_group_rules(db: Database, group_id: int, slot: int, text: str) -> None:
    column = {1: "rules1", 2: "rules2", 3: "rules3"}[slot]
    await db.execute(f"UPDATE groups SET {column} = ? WHERE group_id = ?", (text, group_id))


async def set_active_session(db: Database, group_id: int, session_id: int | None) -> None:
    await db.execute(
        "UPDATE groups SET active_session_id = ? WHERE group_id = ?", (session_id, group_id)
    )


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

async def create_session(db: Database, group_id: int) -> int:
    cur = await db.execute(
        "INSERT INTO sessions (group_id, status) VALUES (?, 'collecting')", (group_id,)
    )
    return cur.lastrowid


async def get_session(db: Database, session_id: int) -> Optional[Row]:
    return await db.fetchone("SELECT * FROM sessions WHERE id = ?", (session_id,))


async def get_open_session(db: Database, group_id: int) -> Optional[Row]:
    """Returns the session that is not yet closed, if any."""
    return await db.fetchone(
        """
        SELECT * FROM sessions
        WHERE group_id = ? AND status != 'closed'
        ORDER BY id DESC LIMIT 1
        """,
        (group_id,),
    )


async def get_last_session(db: Database, group_id: int) -> Optional[Row]:
    return await db.fetchone(
        "SELECT * FROM sessions WHERE group_id = ? ORDER BY id DESC LIMIT 1", (group_id,)
    )


async def update_session_status(db: Database, session_id: int, status: str) -> None:
    if status == "closed":
        await db.execute(
            "UPDATE sessions SET status = ?, closed_at = datetime('now') WHERE id = ?",
            (status, session_id),
        )
    else:
        await db.execute("UPDATE sessions SET status = ? WHERE id = ?", (status, session_id))


async def set_link_reminder_msg(db: Database, session_id: int, msg_id: int | None) -> None:
    await db.execute(
        "UPDATE sessions SET link_reminder_msg_id = ? WHERE id = ?", (msg_id, session_id)
    )


async def set_scam_reminder_msg(db: Database, session_id: int, msg_id: int | None) -> None:
    await db.execute(
        "UPDATE sessions SET scam_reminder_msg_id = ? WHERE id = ?", (msg_id, session_id)
    )


async def get_all_open_sessions(db: Database) -> list[Row]:
    """Used on startup to resume background reminder loops."""
    return await db.fetchall(
        "SELECT * FROM sessions WHERE status IN ('collecting', 'engaging')"
    )


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------

async def get_member(db: Database, session_id: int, telegram_id: int) -> Optional[Row]:
    return await db.fetchone(
        "SELECT * FROM members WHERE session_id = ? AND telegram_id = ?",
        (session_id, telegram_id),
    )


async def get_member_by_id(db: Database, member_id: int) -> Optional[Row]:
    return await db.fetchone("SELECT * FROM members WHERE id = ?", (member_id,))


async def get_member_by_link_message(
    db: Database, session_id: int, message_id: int
) -> Optional[Row]:
    return await db.fetchone(
        "SELECT * FROM members WHERE session_id = ? AND link_message_id = ?",
        (session_id, message_id),
    )


async def create_member(
    db: Database,
    session_id: int,
    group_id: int,
    telegram_id: int,
    username: str | None,
    x_username: str,
    x_link: str,
    tweet_id: str,
    link_message_id: int,
    status: str = "pending",
) -> int:
    cur = await db.execute(
        """
        INSERT INTO members
            (session_id, group_id, telegram_id, username, x_username, x_link,
             tweet_id, link_message_id, status, submitted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            session_id,
            group_id,
            telegram_id,
            username,
            x_username,
            x_link,
            tweet_id,
            link_message_id,
            status,
        ),
    )
    return cur.lastrowid


async def update_member_status(db: Database, member_id: int, status: str) -> None:
    await db.execute(
        "UPDATE members SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, member_id),
    )


async def delete_member(db: Database, member_id: int) -> None:
    await db.execute("DELETE FROM members WHERE id = ?", (member_id,))


async def list_members_by_status(
    db: Database, session_id: int, statuses: list[str]
) -> list[Row]:
    placeholders = ",".join("?" for _ in statuses)
    return await db.fetchall(
        f"SELECT * FROM members WHERE session_id = ? AND status IN ({placeholders}) "
        f"ORDER BY id ASC",
        (session_id, *statuses),
    )


async def list_all_members(db: Database, session_id: int) -> list[Row]:
    return await db.fetchall(
        "SELECT * FROM members WHERE session_id = ? ORDER BY id ASC", (session_id,)
    )


async def count_members_by_status(db: Database, session_id: int) -> dict[str, int]:
    rows = await db.fetchall(
        "SELECT status, COUNT(*) as c FROM members WHERE session_id = ? GROUP BY status",
        (session_id,),
    )
    return {row["status"]: row["c"] for row in rows}


# ---------------------------------------------------------------------------
# x_ownership
# ---------------------------------------------------------------------------

async def get_owner(db: Database, x_username: str) -> Optional[Row]:
    return await db.fetchone(
        "SELECT * FROM x_ownership WHERE x_username = ?", (x_username.lower(),)
    )


async def set_owner(db: Database, x_username: str, telegram_id: int, username: str | None) -> None:
    """First-time ownership claim for an X account. No-op if it's already owned."""
    await db.execute(
        """
        INSERT INTO x_ownership (x_username, telegram_id, username, last_seen_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(x_username) DO NOTHING
        """,
        (x_username.lower(), telegram_id, username),
    )


async def touch_owner(db: Database, x_username: str, username: str | None) -> None:
    """Refreshes last_seen_at (and cached @username) for the CURRENT owner
    re-submitting the same X account they already own."""
    await db.execute(
        "UPDATE x_ownership SET last_seen_at = datetime('now'), username = ? WHERE x_username = ?",
        (username, x_username.lower()),
    )


async def reassign_owner(
    db: Database, x_username: str, telegram_id: int, username: str | None
) -> None:
    """Hands ownership of an X account over to a different Telegram account,
    used when the previous owner was never sanctioned after their last use
    of it (e.g. they lost access to their old account)."""
    await db.execute(
        """
        UPDATE x_ownership
        SET telegram_id = ?, username = ?, last_seen_at = datetime('now')
        WHERE x_username = ?
        """,
        (telegram_id, username, x_username.lower()),
    )


# ---------------------------------------------------------------------------
# telegram_sanctions (mute/ban/suspend history, for X-ownership fraud checks)
# ---------------------------------------------------------------------------

async def record_sanction(db: Database, telegram_id: int, reason: str) -> None:
    """Records that a Telegram account was just sanctioned (muted, banned, or
    suspended). Used to tell a genuinely-lost account apart from a punished
    one when someone else later submits the same X account."""
    await db.execute(
        """
        INSERT INTO telegram_sanctions (telegram_id, last_sanctioned_at, reason)
        VALUES (?, datetime('now'), ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            last_sanctioned_at = excluded.last_sanctioned_at, reason = excluded.reason
        """,
        (telegram_id, reason),
    )


async def get_last_sanction(db: Database, telegram_id: int) -> Optional[Row]:
    return await db.fetchone(
        "SELECT * FROM telegram_sanctions WHERE telegram_id = ?", (telegram_id,)
    )


# ---------------------------------------------------------------------------
# message_log
# ---------------------------------------------------------------------------

async def log_message(
    db: Database,
    session_id: int,
    group_id: int,
    message_id: int,
    telegram_id: int | None,
    kind: str,
) -> None:
    await db.execute(
        """
        INSERT INTO message_log (session_id, group_id, message_id, telegram_id, kind)
        VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, group_id, message_id, telegram_id, kind),
    )


async def list_logged_messages(db: Database, session_id: int) -> list[Row]:
    return await db.fetchall(
        "SELECT * FROM message_log WHERE session_id = ? ORDER BY id ASC", (session_id,)
    )


async def clear_message_log(db: Database, session_id: int) -> None:
    await db.execute("DELETE FROM message_log WHERE session_id = ?", (session_id,))


# ---------------------------------------------------------------------------
# fraud_log
# ---------------------------------------------------------------------------

async def log_fraud(
    db: Database,
    group_id: int,
    session_id: int | None,
    x_username: str,
    owner_telegram_id: int,
    offender_telegram_id: int,
) -> None:
    await db.execute(
        """
        INSERT INTO fraud_log (group_id, session_id, x_username, owner_telegram_id, offender_telegram_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (group_id, session_id, x_username.lower(), owner_telegram_id, offender_telegram_id),
    )


# ---------------------------------------------------------------------------
# user_cache (username -> telegram_id resolution, per group)
# ---------------------------------------------------------------------------

async def cache_user(db: Database, group_id: int, username: str | None, telegram_id: int) -> None:
    if not username:
        return
    await db.execute(
        """
        INSERT INTO user_cache (group_id, username, telegram_id, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(group_id, username) DO UPDATE SET
            telegram_id = excluded.telegram_id, updated_at = excluded.updated_at
        """,
        (group_id, username.lower(), telegram_id),
    )


async def resolve_username(db: Database, group_id: int, username: str) -> Optional[int]:
    username = username.lstrip("@").lower()
    row = await db.fetchone(
        "SELECT telegram_id FROM user_cache WHERE group_id = ? AND username = ?",
        (group_id, username),
    )
    return row["telegram_id"] if row else None
