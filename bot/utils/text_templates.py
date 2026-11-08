from __future__ import annotations

from aiosqlite import Row

from bot.utils.time_utils import fmt_user

LINK_REMINDER_TEXT = "📢 <b>Everyone drop your link.</b>\nOne X (Twitter) post link per person"

# ---------------------------------------------------------------------------
# Confirmation GIFs
# ---------------------------------------------------------------------------
# Paste a direct GIF URL (e.g. a Telegram-friendly .mp4/.gif link) or a
# Telegram file_id here to have that GIF attached to the /begin or /engage
# confirmation message. Leave as "" to send that confirmation as plain text
# (same behavior as before this feature existed).
#
# Suggested themes:
#   BEGIN_GIF  -> unlocking / opening / access being opened
#   ENGAGE_GIF -> opening / unlocking / "let's get started"
BEGIN_GIF = ""   # PASTE_GIF_HERE
ENGAGE_GIF = ""  # PASTE_GIF_HERE

BEGIN_TEXT = (
    "🚀 <b>New session started!</b> The group is open again.\n\n"
    "Drop your X (Twitter) post link below.\n\n"
    "⚠️ Only <b>one link per person</b> is allowed. Editing or deleting your "
    "submission will be detected and flagged automatically."
)

DONE_TEXT = (
    "🔒 <b>Link collection is now closed.</b>\n\n"
    "No further links will be accepted.\n"
    "Session is still opened but paused\n\n"
    "Use /engage to start the video phase."
)

ENGAGE_TEXT = (
    "✅ <b>Check Mode Enabled!!</b>\n\n"
    "•Go to our X ID\n"
    "•Engage with everyone's post, until you get to the Closeed Tweet\n "
    "•Then send your proof as a <b>video</b>\n\n "
    "PS: Caption your video with <code>done</code>, <code>ad</code>, or "
    "<code>all done</code> to be marked SAFE automatically."
)


def scam_list_text(pending_rows: list[Row], header: str = "🚨 <b>Pending / SCAM list</b>") -> str:
    if not pending_rows:
        return f"{header}\n\n✅ No one is pending. Everyone has submitted proof!"

    lines = [header, ""]
    for i, row in enumerate(pending_rows, start=1):
        user_mention = fmt_user(row["telegram_id"], row["username"])
        if row["x_username"]:
            x_user = f"@{row['x_username']}"
        elif row["username"]:
            # X handle couldn't be resolved (e.g. an x.com/i/status/... link)
            # - fall back to their Telegram username instead of "unknown".
            x_user = f"@{row['username']} (TG)"
        else:
            x_user = "no username set"
        lines.append(f"{i}. {user_mention} — X: {x_user}")
    lines.append("")
    lines.append("👆 Please submit your engagement proof video ASAP.")
    return "\n".join(lines)


def status_text(
    session_row: Row,
    submitted_count: int,
    safe_count: int,
    pending_count: int,
    resend_count: int,
) -> str:
    return (
        "📊 <b>Session status</b>\n\n"
        f"•Session ID: <code>{session_row['id']}</code>\n"
        f"•Phase: <b>{session_row['status']}</b>\n\n"
        f"🔗 Links submitted: <b>{submitted_count}</b>\n\n"
        f"✅ Completed (SAFE): <b>{safe_count}</b>\n\n"
        f"⏳ Pending: <b>{pending_count}</b>\n\n"
        f"🔁 Resend queue: <b>{resend_count}</b>"
    )
