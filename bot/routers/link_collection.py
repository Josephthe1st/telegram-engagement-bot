from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from bot.database.db import Database
from bot.services import member_service, session_service
from bot.utils.x_parser import contains_x_link

router = Router(name="link_collection")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
router.edited_message.filter(F.chat.type.in_({"group", "supergroup"}))


def _is_link_message(message: Message) -> bool:
    text = message.text or ""
    if text.startswith("/"):
        return False
    return contains_x_link(message.text) or contains_x_link(message.caption)


@router.message(_is_link_message)
async def on_link_message(message: Message, db: Database) -> None:
    session = await session_service.get_open_session(db, message.chat.id)
    if session is None or session["status"] != "collecting":
        return  # no active link-collection phase, ignore silently
    await member_service.process_link_submission(message.bot, db, message, session)


@router.edited_message()
async def on_link_edited(message: Message, db: Database) -> None:
    session = await session_service.get_open_session(db, message.chat.id)
    if session is None or session["status"] != "collecting":
        return
    await member_service.handle_link_edit(message.bot, db, message, session)
