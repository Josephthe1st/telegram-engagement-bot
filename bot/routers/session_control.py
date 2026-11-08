from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.database import queries as q
from bot.database.db import Database
from bot.logger import get_logger
from bot.services import group_service, session_service
from bot.services.permission_service import require_admin
from bot.services.scheduler_service import (
    start_deletion_watcher,
    start_link_reminder,
    start_scam_reminder,
    stop_all_session_tasks,
)
from bot.utils.text_templates import BEGIN_GIF, BEGIN_TEXT, DONE_TEXT, ENGAGE_GIF, ENGAGE_TEXT

router = Router(name="session_control")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
logger = get_logger(__name__)


async def _send_confirmation(message: Message, text: str, gif: str) -> Message:
    """Sends a confirmation message, attaching `gif` as an animation when one
    is configured (non-empty). Falls back to a plain text message - with the
    exact same text - if no GIF is configured, or if sending the animation
    fails for any reason (bad URL/file_id, etc.)."""
    if gif:
        try:
            return await message.answer_animation(animation=gif, caption=text, parse_mode="HTML")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send confirmation GIF, falling back to text")
    return await message.answer(text, parse_mode="HTML")


@router.message(Command("begin"))
async def cmd_begin(message: Message, db: Database) -> None:
    if not await require_admin(message):
        return
    group_id = message.chat.id

    if not await group_service.is_tracking_enabled(db, group_id):
        await message.reply("⚠️ Link tracking isn't enabled yet. Run /come first.")
        return

    open_session = await session_service.get_open_session(db, group_id)
    if open_session is not None:
        await message.reply(
            f"⚠️ There's already an active session (status: <b>{open_session['status']}</b>). "
            f"Use /close to end it first.",
            parse_mode="HTML",
        )
        return

    session_id = await session_service.start_session(db, message.bot, group_id)
    msg = await _send_confirmation(message, BEGIN_TEXT, BEGIN_GIF)
    try:
        await message.bot.pin_chat_message(group_id, msg.message_id, disable_notification=True)
    except Exception:  # noqa: BLE001
        pass
    await q.set_link_reminder_msg(db, session_id, msg.message_id)
    await q.log_message(db, session_id, group_id, msg.message_id, None, "reminder")

    start_link_reminder(message.bot, db, group_id, session_id)
    start_deletion_watcher(message.bot, db, group_id, session_id)


@router.message(Command("done"))
async def cmd_done(message: Message, db: Database) -> None:
    if not await require_admin(message):
        return
    group_id = message.chat.id
    session = await session_service.get_open_session(db, group_id)
    if session is None or session["status"] != "collecting":
        await message.reply("⚠️ There is no session currently collecting links.")
        return

    await session_service.close_link_collection(db, session["id"])
    stop_all_session_tasks(session["id"])  # stops link reminder + deletion watcher
    await session_service.lock_chat(message.bot, group_id)

    counts = await q.count_members_by_status(db, session["id"])
    submitted = sum(counts.values())
    await message.answer(
        f"{DONE_TEXT}\n\n🔗 Total links submitted: <b>{submitted}</b>", parse_mode="HTML"
    )


@router.message(Command("loc"))
async def cmd_loc(message: Message, db: Database) -> None:
    """Locks the group (admins-only) ahead of a /suspend pass. This does NOT
    end or otherwise change the session's status/lifecycle - only /close
    does that."""
    if not await require_admin(message):
        return
    group_id = message.chat.id
    session = await session_service.get_open_session(db, group_id)
    if session is None:
        await message.reply("⚠️ No active session.")
        return

    await session_service.lock_chat(message.bot, group_id)
    await message.answer(
        "🔒 Group locked (admins-only). Session is still open — use /suspend to mute "
        "pending members, and /close when you're ready to fully end the session.",
        parse_mode="HTML",
    )


@router.message(Command("engage"))
async def cmd_engage(message: Message, db: Database) -> None:
    if not await require_admin(message):
        return
    group_id = message.chat.id
    session = await session_service.get_open_session(db, group_id)
    if session is None or session["status"] not in ("collecting_closed", "collecting"):
        await message.reply(
            "⚠️ Run /done to close link collection before starting engagement."
        )
        return

    await session_service.start_engagement(db, message.bot, group_id, session["id"])
    msg = await _send_confirmation(message, ENGAGE_TEXT, ENGAGE_GIF)
    try:
        await message.bot.pin_chat_message(group_id, msg.message_id, disable_notification=True)
    except Exception:  # noqa: BLE001
        pass
    await q.set_scam_reminder_msg(db, session["id"], msg.message_id)
    await q.log_message(db, session["id"], group_id, msg.message_id, None, "reminder")

    start_scam_reminder(message.bot, db, group_id, session["id"])


@router.message(Command("close"))
async def cmd_close(message: Message, db: Database) -> None:
    if not await require_admin(message):
        return
    group_id = message.chat.id
    session = await session_service.get_open_session(db, group_id)
    if session is None:
        await message.reply("⚠️ There is no active session to close.")
        return

    stop_all_session_tasks(session["id"])
    await session_service.close_session(db, message.bot, group_id, session["id"])
    await message.answer(
        f"🏁 Session <code>{session['id']}</code> has been closed.\n\n"
        f"The group is now locked, only admins can send messages until /begin.",
        parse_mode="HTML",
    )
