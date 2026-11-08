from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject, Update

from bot.database import queries as q
from bot.database.db import Database
from bot.logger import get_logger

logger = get_logger(__name__)

_GROUP_TYPES = {"group", "supergroup"}


class GroupRegistrationMiddleware(BaseMiddleware):
    """Ensures every group the bot sees is present in the DB, keeps a
    lightweight username -> telegram_id cache used by commands like
    /unmute @username, and logs every message sent during an open session
    so /clean can wipe the entire session - not just specially-tracked
    messages (links, videos, reminders)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        db: Database = data["db"]
        message: Message | None = None
        is_new_message = False

        if isinstance(event, Update):
            if event.message is not None:
                message = event.message
                is_new_message = True
            elif event.edited_message is not None:
                message = event.edited_message
        elif isinstance(event, Message):
            message = event
            is_new_message = True

        if message is not None and message.chat and message.chat.type in _GROUP_TYPES:
            try:
                await q.upsert_group(db, message.chat.id, message.chat.title)
                if message.from_user:
                    await q.cache_user(
                        db, message.chat.id, message.from_user.username, message.from_user.id
                    )
                if is_new_message:
                    session = await q.get_open_session(db, message.chat.id)
                    if session is not None:
                        await q.log_message(
                            db,
                            session["id"],
                            message.chat.id,
                            message.message_id,
                            message.from_user.id if message.from_user else None,
                            "user",
                        )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to register group / cache user / log message")

        return await handler(event, data)
