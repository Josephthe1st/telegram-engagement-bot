# X Engagement Bot

A production-ready, multi-group Telegram bot (aiogram 3.x + SQLite) for running
X (Twitter) engagement sessions: link collection engagement proof moderation,
with anti-cheat built in.

## Features

- **Multi-group**: every group has fully independent sessions, members, rules, and reminders.
- **Session lifecycle**: `/come` `/begin` `/done` `/engage` `/close`.
- **Anti-cheat**
  - One X link per person per session (duplicates deleted + warned).
  - Edited-link detection: deletes the edit, publicly shows original vs. edited link.
  - Deleted-link detection: publicly announces who deleted their submission.
  - Permanent X-account ownership: the first Telegram account to submit an X
    username owns it forever. If it's ever submitted by a different Telegram
    account, that account is auto-muted for 18 days and the fraud is announced.
- **Engagement phase**: chat is locked to video-only via Telegram's granular
  `ChatPermissions`. Captions `done` / `ad` / `all done` auto-approve (SAFE).
- **Moderation**: `/scam`, `/safe`, `/resend`, `/mut`, `/ban`, `/unmute`,
  `/suspend`, `/clean`, `/status`.
- **Automatic reminders**: link reminder every 15 min (pinned), scam/proof
  reminder every 20 min (pinned) — both configurable via `.env`.

## Project layout

```
run.py                      entry point
bot/
  app.py                    dispatcher factory, startup/shutdown, router wiring
  config.py                 environment-based settings
  logger.py                 logging setup
  database/
    schema.sql               table definitions
    db.py                     async sqlite wrapper (aiosqlite, WAL mode)
    queries.py                all SQL in one place, typed helper functions
  services/                 business logic (no Telegram-handler concerns)
    group_service.py          group registration, rules storage
    session_service.py        session lifecycle, chat-permission toggling
    member_service.py         anti-cheat: submission / edit / deletion / fraud
    scheduler_service.py      background reminder + deletion-watcher loops
    permission_service.py     admin checks
  middlewares/
    db_middleware.py          injects the shared Database into every handler
    group_registration.py     auto-registers groups + caches usernames
  routers/                  one router per command family
    help.py, rules.py, tracking.py, session_control.py,
    link_collection.py, engagement.py, moderation.py, status.py
  utils/
    x_parser.py                X/Twitter link regex + parsing
    time_utils.py               mention formatting, mute-until helpers
    text_templates.py           all user-facing message templates
  data/
    rules_default_1.txt, rules_default_2.txt   fallback /rs, /rs2 text
```

## Admin access control

By default, "who can run admin commands" is decided per-group by Telegram's
own admin/creator status. If you'd rather have a fixed set of trusted people
control the bot across **all** connected groups regardless of their
in-group role, set `ADMIN_IDS` in `.env`:

```
ADMIN_IDS=111111111,222222222
```

Once this is set, **only** those Telegram user IDs can run admin commands
(`/come`, `/begin`, `/done`, `/engage`, `/loc`, `/close`, `/mut`, `/ban`, `/unmute`,
`/suspend`, `/safe`, `/resend`, `/clean`, `/setrs`, `/setrs2`, `/setrs3`) in any group -
Telegram group-admin status is no longer consulted. Leave it empty and the
bot falls back to each group's own admin/creator status.

Anyone can send `/myid` (in the group or in a DM with the bot) to get the
Telegram ID they need to hand you for this list.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in BOT_TOKEN and (optionally) ADMIN_IDS
python run.py
```

The bot needs to be a group **admin** with rights to: pin messages, delete
messages, restrict/ban members, and change group permissions.

## Command reference

| Command | Who | Description |
|---|---|---|
| `/myid` | anyone | Replies with your Telegram ID (for `ADMIN_IDS`) |
| `/come` | admin | Enables link tracking for the group (required before `/begin`) |
| `/rs`, `/rs2`, `/rs3` | anyone | Sends the rules texts (Rule 3 defaults to "This is Rule 3") |
| `/setrs`, `/setrs2`, `/setrs3` | admin | Edits the stored rules text |
| `/begin` | admin | Starts a session, opens link submissions, starts the 15-min pinned reminder |
| `/done` | admin | Closes link collection, stops the link reminder |
| `/engage` | admin | Locks the chat to video-only, starts the 20-min pinned `/scam` reminder |
| `/scam` | anyone | Lists pending members (Telegram + X username) |
| `/safe` | admin (reply or `@username`) | Manually approves a user's proof |
| `/resend` | admin (reply or `@username`) | Moves a user back to pending, asks them to resend proof |
| `/mut` | admin (reply or `@username`) | Mutes a user; optional duration, e.g. `/mut @username 25d`. No duration = indefinite mute (unchanged default) |
| `/ban` | admin (reply) | Bans the replied user |
| `/unmute` | admin (reply or `@username`) | Unmutes a user |
| `/loc` | admin | Locks the group (admins-only) ahead of `/suspend`. Does **not** end the session |
| `/suspend` | admin | Mutes every still-pending member; optional duration, e.g. `/suspend 25d`, otherwise the configured default. Does **not** end the session |
| `/close` | admin | Ends the session, stops all reminders, restores chat permissions |
| `/clean` | admin | Deletes every message the bot can delete (Bot API permitting) that was logged during the current/last session, including the bot's own messages - never touches database/session records |
| `/status` | anyone | Shows session phase, submitted/safe/pending/resend counts |

## Design notes & known limitations

- **`x.com/i/status/<id>` links**: these don't include the poster's username
  in the URL. The bot tries to resolve the real handle via X's public oEmbed
  endpoint (`publish.twitter.com/oembed`, no API key needed) at submission
  time - if that succeeds, the link is treated exactly like a normal one
  (fraud check included). If it fails (deleted/private tweet, X changes
  the endpoint, network issue), the submission is still tracked, but the
  `/scam` list falls back to showing the person's Telegram username instead
  of a blank "unknown" X handle, and the cross-account ownership fraud check
  is skipped for that submission since there's no handle to check it against.
- **Deleted-message detection**: the Telegram Bot API has no native "message
  deleted" event. `scheduler_service._probe_message_exists` works around this
  by periodically forwarding each pending link message to the same chat and
  immediately deleting the forwarded copy; if the forward fails with
  "message not found", the original was deleted. This is polling-based
  (every `DELETION_CHECK_INTERVAL_MIN` minutes) and best-effort — for
  instant detection you'd need Telegram's MTProto client API (e.g. Pyrogram/
  Telethon) instead of the Bot API.
- **In-memory scheduler**: reminder/watcher loops are `asyncio.Task`s tracked
  in a process-local dict (`scheduler_service._tasks`). On restart,
  `resume_active_sessions()` re-attaches loops to any session that was still
  open in the database. If you ever run multiple bot instances behind a load
  balancer, replace this with a shared job queue (Redis + RQ/Celery, or
  APScheduler with a persistent jobstore).
- **SQLite**: a single aiosqlite connection with WAL mode and an
  `asyncio.Lock` around writes is used. This comfortably handles the write
  volume of engagement-bot traffic; for very large deployments, consider
  Postgres and a connection pool — the `queries.py` module is the only place
  that would need to change.
