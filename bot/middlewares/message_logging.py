from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import Message

from bot.database import queries as q
from bot.database.db import Database
from bot.logger import get_logger

logger = get_logger(__name__)

_GROUP_TYPES = {"group", "supergroup"}


class BotMessageLoggingMiddleware(BaseRequestMiddleware):
    """Intercepts every outgoing Bot API call (sendMessage, sendVideo,
    pinChatMessage, etc.) and logs any Message object the bot produces into
    message_log. Combined with the incoming-message logging in
    GroupRegistrationMiddleware, this means /clean can wipe *every* message
    sent during a session - not just the ones the bot specifically tracks
    for anti-cheat purposes.
    """

    def __init__(self, db: Database):
        super().__init__()
        self.db = db

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> TelegramType:
        response = await make_request(bot, method)
        try:
            await self._log_any_messages(response)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to auto-log an outgoing bot message")
        return response

    async def _log_any_messages(self, response: Any) -> None:
        messages: list[Message] = []
        if isinstance(response, Message):
            messages.append(response)
        elif isinstance(response, list):
            messages.extend(item for item in response if isinstance(item, Message))
        if not messages:
            return

        for msg in messages:
            if msg.chat is None or msg.chat.type not in _GROUP_TYPES:
                continue
            session = await q.get_open_session(self.db, msg.chat.id)
            if session is None:
                continue
            await q.log_message(self.db, session["id"], msg.chat.id, msg.message_id, None, "bot")
