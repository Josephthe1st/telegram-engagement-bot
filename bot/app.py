from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import settings
from bot.database import queries as q
from bot.database.db import Database
from bot.logger import get_logger, setup_logging
from bot.middlewares.db_middleware import DbMiddleware
from bot.middlewares.group_registration import GroupRegistrationMiddleware
from bot.middlewares.message_logging import BotMessageLoggingMiddleware
from bot.routers import (
    engagement,
    help as help_router,
    link_collection,
    moderation,
    rules,
    session_control,
    status,
    tracking,
)
from bot.services.scheduler_service import (
    start_deletion_watcher,
    start_link_reminder,
    start_scam_reminder,
)

logger = get_logger(__name__)


def create_dispatcher(db: Database) -> Dispatcher:
    dp = Dispatcher()

    dp.update.middleware(DbMiddleware(db))
    dp.update.middleware(GroupRegistrationMiddleware())

    # Command routers first, content-detection routers last so that
    # command messages never get swallowed by the link/video handlers.
    dp.include_router(help_router.router)
    dp.include_router(rules.router)
    dp.include_router(tracking.router)
    dp.include_router(session_control.router)
    dp.include_router(moderation.router)
    dp.include_router(status.router)
    dp.include_router(link_collection.router)
    dp.include_router(engagement.router)

    return dp


async def resume_active_sessions(bot: Bot, db: Database) -> None:
    """On startup, restart reminder/watcher loops for sessions that were
    still open when the process last stopped."""
    sessions = await q.get_all_open_sessions(db)
    for session in sessions:
        group_id = session["group_id"]
        session_id = session["id"]
        if session["status"] == "collecting":
            start_link_reminder(bot, db, group_id, session_id)
            start_deletion_watcher(bot, db, group_id, session_id)
            logger.info("Resumed collecting-phase loops for session %s", session_id)
        elif session["status"] == "engaging":
            start_scam_reminder(bot, db, group_id, session_id)
            logger.info("Resumed engaging-phase loop for session %s", session_id)


async def run() -> None:
    setup_logging()

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    db = Database(settings.resolved_db_path())
    await db.connect()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    bot.session.middleware(BotMessageLoggingMiddleware(db))
    dp = create_dispatcher(db)

    try:
        await resume_active_sessions(bot, db)
        logger.info("Bot starting polling...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await db.close()
