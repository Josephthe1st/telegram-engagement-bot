from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import queries as q
from bot.database.db import Database
from bot.services import session_service
from bot.utils.text_templates import status_text

router = Router(name="status")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("status"))
async def cmd_status(message: Message, db: Database) -> None:
    session = await session_service.get_open_session(db, message.chat.id)
    if session is None:
        session = await q.get_last_session(db, message.chat.id)
    if session is None:
        await message.reply("⚠️ No session has ever been started in this group.")
        return

    counts = await q.count_members_by_status(db, session["id"])
    submitted = sum(counts.values())
    safe = counts.get("safe", 0)
    pending = counts.get("pending", 0)
    resend = counts.get("resend", 0)

    await message.answer(
        status_text(session, submitted, safe, pending, resend), parse_mode="HTML"
    )
