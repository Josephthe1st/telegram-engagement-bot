from __future__ import annotations

from aiogram import Bot
from aiogram.types import Message

from bot.config import settings
from bot.logger import get_logger

logger = get_logger(__name__)

_ADMIN_STATUSES = {"administrator", "creator"}


def is_allowlisted_admin(user_id: int) -> bool:
    """True if the user is in the global ADMIN_IDS allowlist."""
    return user_id in settings.admin_ids


async def is_group_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:  # noqa: BLE001 - network/permission errors -> treat as not admin
        logger.exception("Failed to fetch chat member status for admin check")
        return False
    return member.status in _ADMIN_STATUSES


async def is_authorized(bot: Bot, chat_id: int, user_id: int) -> bool:
    """The single source of truth for 'can this user run admin commands?'

    If ADMIN_IDS is configured, ONLY those Telegram user IDs are authorized,
    across every connected group - Telegram's own group-admin/creator status
    is ignored. If ADMIN_IDS is empty, falls back to each group's Telegram
    admin/creator status, so the bot doesn't lock everyone out if it hasn't
    been configured yet.
    """
    if settings.admin_ids:
        return is_allowlisted_admin(user_id)
    return await is_group_admin(bot, chat_id, user_id)


async def require_admin(message: Message) -> bool:
    """Replies with a warning and returns False if the sender is not authorized."""
    if message.from_user is None or message.chat is None:
        return False
    ok = await is_authorized(message.bot, message.chat.id, message.from_user.id)
    if not ok:
        await message.reply("🚫 This command is restricted to authorized admins.")
    return ok
