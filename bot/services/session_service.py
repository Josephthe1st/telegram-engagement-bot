from __future__ import annotations

from aiogram import Bot
from aiogram.types import ChatPermissions
from aiosqlite import Row

from bot.database import queries as q
from bot.database.db import Database
from bot.logger import get_logger

logger = get_logger(__name__)

VIDEO_ONLY_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

NORMAL_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)

# Same as NORMAL_PERMISSIONS but with link previews ("Embed Links") disabled.
# Used specifically when /begin re-opens the group for X-link submissions,
# so members can still send raw X/Twitter URLs but Telegram won't generate
# a preview/thumbnail/card for them.
BEGIN_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=False,
)

# Fully locked: only group admins can post anything. Telegram's chat
# permissions only ever restrict non-admin members, so admins are
# automatically exempt from this - no separate admin allowlist needed.
LOCKED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)


async def start_session(db: Database, bot: Bot, group_id: int) -> int:
    """Creates a new session and re-opens the chat for everyone, in case a
    previous session left it locked via /close. Link previews are disabled
    so members can post X/Twitter links without Telegram generating a
    preview card/thumbnail for them."""
    session_id = await q.create_session(db, group_id)
    await q.set_active_session(db, group_id, session_id)
    try:
        await bot.set_chat_permissions(group_id, BEGIN_PERMISSIONS)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to reopen chat permissions on session start")
    return session_id


async def get_open_session(db: Database, group_id: int) -> Row | None:
    return await q.get_open_session(db, group_id)


async def lock_chat(bot: Bot, group_id: int) -> None:
    """Locks the chat down to admins-only. Used by /done (pending /engage)
    and /close (session fully ended)."""
    try:
        await bot.set_chat_permissions(group_id, LOCKED_PERMISSIONS)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to lock chat permissions for %s", group_id)


async def close_link_collection(db: Database, session_id: int) -> None:
    await q.update_session_status(db, session_id, "collecting_closed")


async def start_engagement(db: Database, bot: Bot, group_id: int, session_id: int) -> None:
    await q.update_session_status(db, session_id, "engaging")
    try:
        await bot.set_chat_permissions(group_id, VIDEO_ONLY_PERMISSIONS)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to restrict chat permissions for engagement phase")


async def close_session(db: Database, bot: Bot, group_id: int, session_id: int) -> None:
    """Ends the session and locks the chat so only admins can send anything,
    until the next /begin reopens it."""
    await q.update_session_status(db, session_id, "closed")
    await q.set_active_session(db, group_id, None)
    await lock_chat(bot, group_id)
