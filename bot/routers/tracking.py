from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.database.db import Database
from bot.services import group_service
from bot.services.permission_service import require_admin

router = Router(name="tracking")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(Command("come"))
async def cmd_come(message: Message, db: Database) -> None:
    if not await require_admin(message):
        return
    await group_service.enable_tracking(db, message.chat.id)
    await message.reply(
        "✅ Link tracking is now <b>enabled</b> for this group. "
        "You can now use /begin to start a session.",
        parse_mode="HTML",
    )
