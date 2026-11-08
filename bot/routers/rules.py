from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import LinkPreviewOptions, Message

from bot.database.db import Database
from bot.services import group_service
from bot.services.permission_service import require_admin

router = Router(name="rules")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


@router.message(Command("rs"))
async def cmd_rs(message: Message, db: Database) -> None:
    text = await group_service.get_rules(db, message.chat.id, slot=1)
    await message.answer(text, link_preview_options=_NO_PREVIEW)


@router.message(Command("rs2"))
async def cmd_rs2(message: Message, db: Database) -> None:
    text = await group_service.get_rules(db, message.chat.id, slot=2)
    await message.answer(text, link_preview_options=_NO_PREVIEW)


@router.message(Command("rs3"))
async def cmd_rs3(message: Message, db: Database) -> None:
    text = await group_service.get_rules(db, message.chat.id, slot=3)
    await message.answer(text, link_preview_options=_NO_PREVIEW)


@router.message(Command("setrs"))
async def cmd_setrs(message: Message, db: Database, command: CommandObject) -> None:
    if not await require_admin(message):
        return
    if not command.args:
        await message.reply("Usage: /setrs <new rules text>")
        return
    await group_service.set_rules(db, message.chat.id, slot=1, text=command.args)
    await message.reply("✅ Rules (1/2) updated.")


@router.message(Command("setrs2"))
async def cmd_setrs2(message: Message, db: Database, command: CommandObject) -> None:
    if not await require_admin(message):
        return
    if not command.args:
        await message.reply("Usage: /setrs2 <new rules text>")
        return
    await group_service.set_rules(db, message.chat.id, slot=2, text=command.args)
    await message.reply("✅ Rules (2/2) updated.")


@router.message(Command("setrs3"))
async def cmd_setrs3(message: Message, db: Database, command: CommandObject) -> None:
    if not await require_admin(message):
        return
    if not command.args:
        await message.reply("Usage: /setrs3 <new rule 3 text>")
        return
    await group_service.set_rules(db, message.chat.id, slot=3, text=command.args)
    await message.reply("✅ Rule 3 updated.")
