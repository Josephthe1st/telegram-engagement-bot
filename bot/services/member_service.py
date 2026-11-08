from __future__ import annotations

from aiogram import Bot
from aiogram.types import ChatPermissions, Message
from aiosqlite import Row

from bot.config import settings
from bot.database import queries as q
from bot.database.db import Database
from bot.logger import get_logger
from bot.utils.time_utils import fmt_user, mute_until
from bot.utils.x_parser import XLink, extract_x_link, resolve_username_from_tweet

logger = get_logger(__name__)

FULL_MUTE = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

DONE_CAPTION_PATTERNS = {"done", "ad", "all done", "alldone"}


async def _safe_delete(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:  # noqa: BLE001
        logger.debug("Could not delete message %s in %s (already gone?)", message_id, chat_id)


async def _check_x_ownership(
    db: Database, x_username: str, telegram_id: int, username: str | None
) -> Row | None:
    """Decides what should happen when `telegram_id` submits `x_username`.

    Returns the blocking owner Row if this submission should be treated as
    fraud (a different Telegram account trying to use an X account whose
    previous user was sanctioned after their last use of it), or None if the
    submission may proceed normally.

    - Never seen before -> claim it for this account.
    - Same account that already owns it -> just refresh last-used time.
    - A different account owns it:
        - If that owner was muted/banned/suspended at or after their last use
          of this X account -> this is a genuine alt-account attempt, block it.
        - Otherwise (owner was never sanctioned, e.g. they simply lost access
          to their old Telegram account) -> hand ownership over to the new
          account and let the submission through normally.
    """
    owner = await q.get_owner(db, x_username)
    if owner is None:
        await q.set_owner(db, x_username, telegram_id, username)
        return None

    if owner["telegram_id"] == telegram_id:
        await q.touch_owner(db, x_username, username)
        return None

    sanction = await q.get_last_sanction(db, owner["telegram_id"])
    owner_sanctioned_after_last_use = (
        sanction is not None and sanction["last_sanctioned_at"] >= owner["last_seen_at"]
    )
    if owner_sanctioned_after_last_use:
        return owner

    await q.reassign_owner(db, x_username, telegram_id, username)
    return None


async def process_link_submission(bot: Bot, db: Database, message: Message, session: Row) -> None:
    """Handles a new incoming X link during the collecting phase, including
    duplicate detection and permanent-ownership fraud detection."""
    text = message.text or message.caption
    xlink = extract_x_link(text)
    if xlink is None:
        return

    telegram_id = message.from_user.id
    username = message.from_user.username
    group_id = message.chat.id
    session_id = session["id"]

    await q.cache_user(db, group_id, username, telegram_id)

    # 1. one link per person per session
    existing = await q.get_member(db, session_id, telegram_id)
    if existing is not None:
        await _safe_delete(bot, group_id, message.message_id)
        mention = fmt_user(telegram_id, username)
        await message.answer(
            f"⚠️ {mention}, you already submitted a link this session. "
            f"Your new message was deleted — only one link per person is allowed.",
            parse_mode="HTML",
        )
        return

    # 2. For links that don't expose a username in the URL (x.com/i/status/<id>),
    # try to resolve the poster's real handle via X's public oEmbed endpoint.
    # This is the only way to run the cross-account fraud check on these
    # links - if it fails (deleted/private tweet, network hiccup, etc.) we
    # fall back to tracking the submission without a known X username.
    if xlink.username is None:
        resolved = await resolve_username_from_tweet(xlink.tweet_id)
        if resolved:
            xlink = XLink(
                username=resolved,
                tweet_id=xlink.tweet_id,
                canonical_url=f"https://x.com/{resolved}/status/{xlink.tweet_id}",
            )
            logger.info("Resolved username @%s for tweet %s via oEmbed", resolved, xlink.tweet_id)
        else:
            logger.info("Could not resolve a username for tweet %s (i/status link)", xlink.tweet_id)

    # 3. permanent X-account ownership / fraud check.
    # Only runs when we actually know the username - otherwise there's
    # nothing to check ownership against.
    if xlink.username is not None:
        blocking_owner = await _check_x_ownership(db, xlink.username, telegram_id, username)
        if blocking_owner is not None:
            await _fraud_detected(bot, db, message, xlink, blocking_owner)
            return

    member_id = await q.create_member(
        db,
        session_id=session_id,
        group_id=group_id,
        telegram_id=telegram_id,
        username=username,
        x_username=xlink.username,
        x_link=xlink.canonical_url,
        tweet_id=xlink.tweet_id,
        link_message_id=message.message_id,
    )
    await q.log_message(db, session_id, group_id, message.message_id, telegram_id, "link")
    logger.info("Link submitted: member_id=%s user=%s x=@%s", member_id, telegram_id, xlink.username)
    # Intentionally no confirmation reply here - tracking should be silent so
    # the group doesn't get crowded with bot replies for every submission.


async def _fraud_detected(
    bot: Bot, db: Database, message: Message, xlink: XLink, owner: Row
) -> None:
    group_id = message.chat.id
    telegram_id = message.from_user.id
    username = message.from_user.username
    session_id = None
    open_session = await q.get_open_session(db, group_id)
    if open_session is not None:
        session_id = open_session["id"]

    await _safe_delete(bot, group_id, message.message_id)

    until = mute_until(settings.fraud_mute_days)
    try:
        await bot.restrict_chat_member(group_id, telegram_id, permissions=FULL_MUTE, until_date=until)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to mute fraudulent user %s in %s", telegram_id, group_id)
    await q.record_sanction(db, telegram_id, "x_ownership_fraud")

    await q.log_fraud(db, group_id, session_id, xlink.username, owner["telegram_id"], telegram_id)

    owner_mention = fmt_user(owner["telegram_id"], owner["username"])
    offender_mention = fmt_user(telegram_id, username)
    text = (
        "🚨 <b>Fraud detected!</b>\n"
        f"{offender_mention} attempted to submit X account <b>@{xlink.username}</b>, "
        f"which is permanently linked to {owner_mention}.\n\n"
        f"{offender_mention} has been muted for <b>{settings.fraud_mute_days} days</b>."
    )
    await bot.send_message(group_id, text, parse_mode="HTML")
    logger.warning(
        "Fraud: x=@%s owner=%s offender=%s group=%s",
        xlink.username, owner["telegram_id"], telegram_id, group_id,
    )


async def handle_link_edit(bot: Bot, db: Database, edited_message: Message, session: Row) -> None:
    """Detects an edit to a previously-submitted link message."""
    session_id = session["id"]
    group_id = edited_message.chat.id
    member = await q.get_member_by_link_message(db, session_id, edited_message.message_id)
    if member is None:
        return

    new_text = edited_message.text or edited_message.caption
    new_link = extract_x_link(new_text)
    original_link = member["x_link"]

    await _safe_delete(bot, group_id, edited_message.message_id)
    await q.delete_member(db, member["id"])

    mention = fmt_user(member["telegram_id"], member["username"])
    edited_display = new_link.canonical_url if new_link else "(invalid / removed link)"
    text = (
        "✏️ <b>Edited link detected!</b>\n"
        f"{mention} edited their submitted link after posting. The edited message "
        "has been deleted.\n\n"
        f"<b>Original:</b> {original_link}\n\n"
        f"<b>Edited:</b> {edited_display}\n\n"
        "Editing of message is not allowed, Resubmit the initial link before the session closes."
    )
    await bot.send_message(group_id, text, parse_mode="HTML")
    logger.warning("Edited link detected for member_id=%s in session=%s", member["id"], session_id)


async def handle_link_deleted(bot: Bot, db: Database, member: Row) -> None:
    """Called by the deletion watcher once it confirms a submitted link message
    no longer exists in the chat."""
    mention = fmt_user(member["telegram_id"], member["username"])
    text = (
        "🚫 <b>Deleting Detected!</b>\n"
        f"{mention} deleted their submitted link (<code>{member['x_link']}</code>). "
        "Admin Please Review"
    )
    await bot.send_message(member["group_id"], text, parse_mode="HTML")
    await q.delete_member(db, member["id"])
    logger.warning("Detected deleted link submission for member_id=%s", member["id"])


def caption_marks_done(caption: str | None) -> bool:
    if not caption:
        return False
    normalized = caption.strip().lower()
    return normalized in DONE_CAPTION_PATTERNS
