from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="help")

HELP_TEXT = (
    "🤖 <b>X Engagement Bot</b>\n\n"
    "<b>Setup</b>\n"
    "/myid — get your Telegram ID to add to ADMIN_IDS\n"
    "/come — enable link tracking in this group\n"
    "/rs, /rs2, /rs3 — show group rules\n"
    "/setrs, /setrs2, /setrs3 — (admin) edit rules text\n\n"
    "<b>Session flow</b>\n"
    "/begin — start a new session, open link submissions\n"
    "/done — close link collection\n"
    "/engage — start engagement phase (video-only chat)\n"
    "/loc — lock the group (admins-only) ahead of /suspend; session stays open\n"
    "/suspend — mute everyone still pending (add a duration like 25d to override the default)\n"
    "/close — end the session entirely, stops all reminders\n\n"
    "<b>Moderation</b>\n"
    "/scam — list pending members\n"
    "/safe — (reply or @username) approve a member's proof\n"
    "/resend — (reply or @username) request a new proof video\n"
    "/mut — (reply or @username) mute a member, optionally with a duration like 25d\n"
    "/ban — (reply) ban a member\n"
    "/unmute — (reply or @username) unmute a member\n"
    "/clean — delete all session messages\n"
    "/status — show session statistics"
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Hi! Add me to a group as admin and run /come to get started, or /help for the full command list."
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="HTML")


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    """Lets anyone look up their own Telegram ID, so an admin can be added
    to the ADMIN_IDS list in .env without guesswork."""
    user = message.from_user
    if user is None:
        return
    await message.reply(
        f"🆔 Your Telegram ID is: <code>{user.id}</code>\n"
        "Add it to <code>ADMIN_IDS</code> in the bot's .env file to become an authorized admin.",
        parse_mode="HTML",
    )
