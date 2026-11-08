from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.config import settings
from bot.database import queries as q
from bot.database.db import Database
from bot.logger import get_logger
from bot.services import session_service
from bot.services.member_service import FULL_MUTE
from bot.services.permission_service import require_admin
from bot.services.scheduler_service import send_scam_list_now
from bot.utils.time_utils import fmt_user, mute_until, mute_until_delta, parse_duration

router = Router(name="moderation")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
logger = get_logger(__name__)


def _target_from_reply(message: Message):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    return None


async def _resolve_username_arg(
    db: Database, chat_id: int, raw_username: str
) -> tuple[int, str] | None:
    """Resolves a raw '@username' (or 'username') argument to a
    (telegram_id, display_label) pair via the user_cache, or None if it
    can't be resolved (the user hasn't sent a message since the bot joined).
    """
    username = raw_username.strip().lstrip("@")
    resolved = await q.resolve_username(db, chat_id, username)
    if resolved is None:
        return None
    return resolved, f"@{username}"


@router.message(Command("scam"))
async def cmd_scam(message: Message, db: Database) -> None:
    session = await session_service.get_open_session(db, message.chat.id)
    if session is None:
        await message.reply("⚠️ No active session.")
        return
    await send_scam_list_now(message.bot, db, message.chat.id, session["id"])


@router.message(Command("mut"))
async def cmd_mut(message: Message, db: Database, command: CommandObject) -> None:
    """Mutes a user, by reply or by @username. An optional trailing/leading
    duration argument (e.g. '25d') can appear in either order:
    /mut, /mut 25d, /mut @username, /mut @username 25d.
    With no duration given, the existing default (an indefinite mute, same
    as before this change) is kept.
    """
    if not await require_admin(message):
        return

    tokens = command.args.split() if command.args else []
    duration_token: str | None = None
    duration = None
    username_token: str | None = None
    for token in tokens:
        parsed = parse_duration(token)
        if parsed is not None:
            duration = parsed
            duration_token = token
        elif token.startswith("@"):
            username_token = token

    target = _target_from_reply(message)
    if target is not None:
        target_id = target.id
        target_label = fmt_user(target.id, target.username)
    elif username_token is not None:
        resolved = await _resolve_username_arg(db, message.chat.id, username_token)
        if resolved is None:
            await message.reply(
                "⚠️ Couldn't resolve that username, they need to have sent at least one "
                "message in this group since I joined. Try replying to their message instead."
            )
            return
        target_id, target_label = resolved
    else:
        await message.reply(
            "Usage: reply to a user with /mut, or use /mut @username — optionally add a "
            "duration, e.g. /mut @username 25d."
        )
        return

    until = mute_until_delta(duration) if duration is not None else None
    try:
        await message.bot.restrict_chat_member(
            message.chat.id, target_id, permissions=FULL_MUTE, until_date=until
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to mute user %s", target_id)
        await message.reply("❌ Failed to mute — check my admin permissions.")
        return
    await q.record_sanction(db, target_id, "mut")

    if duration_token is not None:
        await message.answer(
            f"🔇 {target_label} has been muted for {duration_token}.", parse_mode="HTML"
        )
    else:
        await message.answer(f"🔇 {target_label} has been muted.", parse_mode="HTML")


@router.message(Command("ban"))
async def cmd_ban(message: Message, db: Database) -> None:
    if not await require_admin(message):
        return
    target = _target_from_reply(message)
    if target is None:
        await message.reply("Reply to a user's message with /ban to ban them.")
        return
    try:
        await message.bot.ban_chat_member(message.chat.id, target.id)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to ban user %s", target.id)
        await message.reply("❌ Failed to ban — check my admin permissions.")
        return
    await q.record_sanction(db, target.id, "ban")
    mention = fmt_user(target.id, target.username)
    await message.answer(f"🚫 {mention} has been banned.", parse_mode="HTML")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, db: Database, command: CommandObject) -> None:
    if not await require_admin(message):
        return

    target_id = None
    target_label = None

    target = _target_from_reply(message)
    if target is not None:
        target_id = target.id
        target_label = fmt_user(target.id, target.username)
    elif command.args:
        username = command.args.strip()
        resolved = await q.resolve_username(db, message.chat.id, username)
        if resolved is None:
            await message.reply(
                "⚠️ Couldn't resolve that username, they need to have sent at least one "
                "message in this group since I joined. Try replying to their message instead."
            )
            return
        target_id = resolved
        target_label = f"@{username.lstrip('@')}"
    else:
        await message.reply("Usage: reply to a user with /unmute, or use /unmute @username")
        return

    try:
        await message.bot.restrict_chat_member(
            message.chat.id, target_id, permissions=session_service.NORMAL_PERMISSIONS
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to unmute user %s", target_id)
        await message.reply("❌ Failed to unmute — check my admin permissions.")
        return
    await message.answer(f"🔊 {target_label} has been unmuted.", parse_mode="HTML")


@router.message(Command("suspend"))
async def cmd_suspend(message: Message, db: Database, command: CommandObject) -> None:
    """Suspends (mutes) every still-pending member. Supports an optional
    custom duration, e.g. /suspend 25d — falls back to the configured
    SUSPEND_MUTE_DAYS default when no duration is given. Suspending does
    NOT close or otherwise end the session.
    """
    if not await require_admin(message):
        return
    session = await session_service.get_open_session(db, message.chat.id)
    if session is None:
        await message.reply("⚠️ No active session.")
        return

    pending = await q.list_members_by_status(db, session["id"], ["pending", "resend"])
    if not pending:
        await message.reply("✅ Nobody is pending — nothing to suspend.")
        return

    duration_label = f"{settings.suspend_mute_days} days"
    until = mute_until(settings.suspend_mute_days)
    if command.args:
        parsed = parse_duration(command.args.strip())
        if parsed is not None:
            until = mute_until_delta(parsed)
            duration_label = command.args.strip()

    muted_mentions = []
    for member in pending:
        try:
            await message.bot.restrict_chat_member(
                message.chat.id, member["telegram_id"], permissions=FULL_MUTE, until_date=until
            )
            muted_mentions.append(fmt_user(member["telegram_id"], member["username"]))
            await q.record_sanction(db, member["telegram_id"], "suspend")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to suspend user %s", member["telegram_id"])

    text = (
        f"⛔ <b>{len(muted_mentions)} member(s) suspended for {duration_label}</b> "
        "for not completing engagement:\n\n" + "\n".join(muted_mentions)
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("safe"))
async def cmd_safe(message: Message, db: Database, command: CommandObject) -> None:
    """Approves a member's proof. Reply to their proof video, or use
    /safe @username."""
    if not await require_admin(message):
        return

    target = _target_from_reply(message)
    if target is not None:
        target_id = target.id
        target_label = fmt_user(target.id, target.username)
    elif command.args:
        resolved = await _resolve_username_arg(db, message.chat.id, command.args)
        if resolved is None:
            await message.reply(
                "⚠️ Couldn't resolve that username, they need to have sent at least one "
                "message in this group since I joined. Try replying to their proof message instead."
            )
            return
        target_id, target_label = resolved
    else:
        await message.reply(
            "Reply to a user's proof video with /safe to approve them, or use /safe @username."
        )
        return

    session = await session_service.get_open_session(db, message.chat.id)
    if session is None:
        await message.reply("⚠️ No active session.")
        return
    member = await q.get_member(db, session["id"], target_id)
    if member is None:
        await message.reply("⚠️ That user has no submission on record for this session.")
        return
    await q.update_member_status(db, member["id"], "safe")
    await message.answer(f"✅ {target_label} manually marked SAFE by an admin.", parse_mode="HTML")


@router.message(Command("resend"))
async def cmd_resend(message: Message, db: Database, command: CommandObject) -> None:
    """Moves a member back to the pending/resend queue and asks them to
    resend proof. Works by reply or by /resend @username."""
    if not await require_admin(message):
        return

    target = _target_from_reply(message)
    if target is not None:
        target_id = target.id
        target_label = fmt_user(target.id, target.username)
    elif command.args:
        resolved = await _resolve_username_arg(db, message.chat.id, command.args)
        if resolved is None:
            await message.reply(
                "⚠️ Couldn't resolve that username, they need to have sent at least one "
                "message in this group since I joined. Try replying to their message instead."
            )
            return
        target_id, target_label = resolved
    else:
        await message.reply(
            "Reply to a user with /resend to request a new proof video, or use /resend @username."
        )
        return

    session = await session_service.get_open_session(db, message.chat.id)
    if session is None:
        await message.reply("⚠️ No active session.")
        return
    member = await q.get_member(db, session["id"], target_id)
    if member is None:
        await message.reply("⚠️ That user has no submission on record for this session.")
        return
    await q.update_member_status(db, member["id"], "resend")
    await message.answer(
        f"🔁 {target_label}, You did not carry out the task properly, make sure you followed all the rules.\n\n "
        f"Submit a proper screen recording showing you completed the task, with your X profile visible. "
        f"Resend your screen recording proof.",
        parse_mode="HTML",
    )


@router.message(Command("clean"))
async def cmd_clean(message: Message, db: Database) -> None:
    if not await require_admin(message):
        return
    session = await session_service.get_open_session(db, message.chat.id)
    if session is None:
        session = await q.get_last_session(db, message.chat.id)
    if session is None:
        await message.reply("⚠️ No session found for this group.")
        return

    logs = await q.list_logged_messages(db, session["id"])
    deleted = 0
    for row in logs:
        try:
            await message.bot.delete_message(message.chat.id, row["message_id"])
            deleted += 1
        except Exception:  # noqa: BLE001
            pass
    await q.clear_message_log(db, session["id"])

    confirmation = await message.answer(f"🧹 Cleaned {deleted} session message(s).")
    try:
        await message.bot.delete_message(message.chat.id, message.message_id)
    except Exception:  # noqa: BLE001
        pass
