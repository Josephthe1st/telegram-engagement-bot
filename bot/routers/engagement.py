from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from bot.database import queries as q
from bot.database.db import Database
from bot.services import member_service, session_service
from bot.utils.time_utils import fmt_user

router = Router(name="engagement")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))


@router.message(F.video | F.video_note)
async def on_proof_video(message: Message, db: Database) -> None:
    session = await session_service.get_open_session(db, message.chat.id)
    if session is None or session["status"] != "engaging":
        return

    telegram_id = message.from_user.id
    member = await q.get_member(db, session["id"], telegram_id)
    if member is None:
        await message.reply(
            "⚠️ We don't have a link submission on record for you this session, "
            "please contact an admin."
        )
        return

    await q.log_message(db, session["id"], message.chat.id, message.message_id, telegram_id, "video")

    caption = message.caption
    if member_service.caption_marks_done(caption):
        await q.update_member_status(db, member["id"], "safe")
        mention = fmt_user(telegram_id, message.from_user.username)
        await message.reply(f"✅ {mention} marked as SAFE. Link tracked and encrypted!", parse_mode="HTML")
    else:
        await message.reply(
            "📹 Proof received. Caption it with \"done\", \"ad\", or \"all done\" next time "
            "for automatic approval, an admin will review this one."
        )
