from __future__ import annotations

import asyncio
from typing import Literal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from bot.config import settings
from bot.database import queries as q
from bot.database.db import Database
from bot.logger import get_logger
from bot.services.member_service import handle_link_deleted
from bot.utils.text_templates import LINK_REMINDER_TEXT, scam_list_text

logger = get_logger(__name__)

TaskKind = Literal["link", "scam", "deletion"]

# In-memory registry of running background tasks, keyed by (session_id, kind).
# NOTE: this state is per-process. If you run multiple bot instances behind a
# load balancer you must switch to a shared job queue (e.g. Redis + RQ/Celery
# or APScheduler with a persistent jobstore) instead of this in-memory dict.
_tasks: dict[tuple[int, str], asyncio.Task] = {}


def _register(session_id: int, kind: TaskKind, task: asyncio.Task) -> None:
    key = (session_id, kind)
    existing = _tasks.get(key)
    if existing and not existing.done():
        existing.cancel()
    _tasks[key] = task


def _cancel(session_id: int, kind: TaskKind) -> None:
    key = (session_id, kind)
    task = _tasks.pop(key, None)
    if task and not task.done():
        task.cancel()


def stop_all_session_tasks(session_id: int) -> None:
    for kind in ("link", "scam", "deletion"):
        _cancel(session_id, kind)


# ---------------------------------------------------------------------------
# Link reminder (every N minutes while collecting)
# ---------------------------------------------------------------------------

async def _send_and_pin_link_reminder(bot: Bot, db: Database, group_id: int, session_id: int) -> None:
    session = await q.get_session(db, session_id)
    if session is None:
        return
    if session["link_reminder_msg_id"]:
        try:
            await bot.unpin_chat_message(group_id, session["link_reminder_msg_id"])
        except Exception:  # noqa: BLE001
            pass
    msg = await bot.send_message(group_id, LINK_REMINDER_TEXT, parse_mode="HTML")
    try:
        await bot.pin_chat_message(group_id, msg.message_id, disable_notification=True)
    except Exception:  # noqa: BLE001
        logger.warning("Could not pin link reminder in %s (missing rights?)", group_id)
    await q.set_link_reminder_msg(db, session_id, msg.message_id)
    await q.log_message(db, session_id, group_id, msg.message_id, None, "reminder")


async def _link_reminder_loop(bot: Bot, db: Database, group_id: int, session_id: int) -> None:
    interval = settings.link_reminder_interval_min * 60
    try:
        while True:
            await asyncio.sleep(interval)
            session = await q.get_session(db, session_id)
            if session is None or session["status"] != "collecting":
                return
            await _send_and_pin_link_reminder(bot, db, group_id, session_id)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Link reminder loop crashed for session %s", session_id)


def start_link_reminder(bot: Bot, db: Database, group_id: int, session_id: int) -> None:
    task = asyncio.create_task(_link_reminder_loop(bot, db, group_id, session_id))
    _register(session_id, "link", task)


# ---------------------------------------------------------------------------
# Deletion watcher (every N minutes while collecting) - probe-based, since
# the Bot API has no native "message deleted" event.
# ---------------------------------------------------------------------------

async def _probe_message_exists(bot: Bot, group_id: int, message_id: int) -> bool:
    """Best-effort check for whether a message still exists, by forwarding it
    to itself and immediately deleting the forwarded copy. If the original
    was deleted, Telegram raises a BadRequest."""
    try:
        fwd = await bot.forward_message(
            chat_id=group_id, from_chat_id=group_id, message_id=message_id, disable_notification=True
        )
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "not found" in msg or "message_id_invalid" in msg or "can't be forwarded" not in msg:
            return False
        # Some other bad request (e.g. forwarding restricted) - assume it exists
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error probing message %s in %s", message_id, group_id)
        return True

    try:
        await bot.delete_message(group_id, fwd.message_id)
    except Exception:  # noqa: BLE001
        pass
    return True


async def _deletion_watch_loop(bot: Bot, db: Database, group_id: int, session_id: int) -> None:
    interval = settings.deletion_check_interval_min * 60
    try:
        while True:
            await asyncio.sleep(interval)
            session = await q.get_session(db, session_id)
            if session is None or session["status"] != "collecting":
                return
            pending = await q.list_members_by_status(db, session_id, ["pending"])
            for member in pending:
                if not member["link_message_id"]:
                    continue
                exists = await _probe_message_exists(bot, group_id, member["link_message_id"])
                if not exists:
                    await handle_link_deleted(bot, db, member)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Deletion watcher crashed for session %s", session_id)


def start_deletion_watcher(bot: Bot, db: Database, group_id: int, session_id: int) -> None:
    task = asyncio.create_task(_deletion_watch_loop(bot, db, group_id, session_id))
    _register(session_id, "deletion", task)


# ---------------------------------------------------------------------------
# Scam reminder (every N minutes while engaging)
# ---------------------------------------------------------------------------

async def _send_and_pin_scam_reminder(bot: Bot, db: Database, group_id: int, session_id: int) -> None:
    session = await q.get_session(db, session_id)
    if session is None:
        return
    pending = await q.list_members_by_status(db, session_id, ["pending", "resend"])
    text = scam_list_text(pending)

    if session["scam_reminder_msg_id"]:
        try:
            await bot.unpin_chat_message(group_id, session["scam_reminder_msg_id"])
        except Exception:  # noqa: BLE001
            pass

    msg = await bot.send_message(group_id, text, parse_mode="HTML")
    try:
        await bot.pin_chat_message(group_id, msg.message_id, disable_notification=True)
    except Exception:  # noqa: BLE001
        logger.warning("Could not pin scam reminder in %s (missing rights?)", group_id)
    await q.set_scam_reminder_msg(db, session_id, msg.message_id)
    await q.log_message(db, session_id, group_id, msg.message_id, None, "reminder")


async def _scam_reminder_loop(bot: Bot, db: Database, group_id: int, session_id: int) -> None:
    interval = settings.scam_reminder_interval_min * 60
    try:
        while True:
            await asyncio.sleep(interval)
            session = await q.get_session(db, session_id)
            if session is None or session["status"] != "engaging":
                return
            await _send_and_pin_scam_reminder(bot, db, group_id, session_id)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Scam reminder loop crashed for session %s", session_id)


def start_scam_reminder(bot: Bot, db: Database, group_id: int, session_id: int) -> None:
    task = asyncio.create_task(_scam_reminder_loop(bot, db, group_id, session_id))
    _register(session_id, "scam", task)


async def send_scam_list_now(bot: Bot, db: Database, group_id: int, session_id: int) -> None:
    """Used by the /scam command for an on-demand (non-pinned) listing."""
    pending = await q.list_members_by_status(db, session_id, ["pending", "resend"])
    text = scam_list_text(pending)
    await bot.send_message(group_id, text, parse_mode="HTML")
