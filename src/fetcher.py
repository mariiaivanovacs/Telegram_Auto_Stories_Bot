import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import src.db as db
from src.config import get_settings
from src.parser import normalize

# Telethon is an optional runtime dependency. Delay imports to runtime so the
# module can be imported in environments without telethon (tests, linters).
try:
    from telethon import TelegramClient
    from telethon.errors import (
        BotMethodInvalidError,
        ChannelPrivateError,
        FloodWaitError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
    )
    _TELETHON_AVAILABLE = True
except Exception:  # noqa: BLE001
    TelegramClient = None
    BotMethodInvalidError = Exception
    ChannelPrivateError = Exception
    FloodWaitError = Exception
    UsernameInvalidError = Exception
    UsernameNotOccupiedError = Exception
    _TELETHON_AVAILABLE = False

logger = logging.getLogger(__name__)

SESSION_PATH = "data/userbot.session"
MAX_MESSAGES_PER_CHANNEL = 10
MAX_MESSAGE_AGE_DAYS = 30
ITERATION_LIMIT_PER_CHANNEL = 100


class NotAuthenticatedError(RuntimeError):
    """Raised when the userbot session is missing or expired."""


def _error_hint(exc: Exception) -> str:
    """Return a plain-language reason for a channel fetch failure."""
    name = type(exc).__name__
    hints = {
        "BotMethodInvalidError": (
            "the saved userbot session belongs to a Telegram bot account, "
            "so Telegram blocks reading channel history — run /auth and log in "
            "with a real user phone number"
        ),
        "ChannelPrivateError": (
            "channel is private — the userbot account must join it first"
        ),
        "UsernameNotOccupiedError": (
            "username does not exist — fix the spelling in config.yaml"
        ),
        "UsernameInvalidError": (
            "username format is invalid — check for typos in config.yaml"
        ),
        "UserNotParticipantError": (
            "userbot is not a member — join the channel from the userbot account"
        ),
    }
    return hints.get(name, name)


async def _fetch_channel(
    client: TelegramClient,
    username: str,
    run_id: int,
    cutoff: datetime,
) -> int:
    """Fetch recent text messages from one channel. Returns count stored."""
    channel_id = db.get_channel_id(username)
    if channel_id is None:
        logger.warning("Channel %s missing from DB, skipping", username)
        return 0

    count = 0
    try:
        async for msg in client.iter_messages(username, limit=ITERATION_LIMIT_PER_CHANNEL):
            if not msg.text or msg.date is None:
                continue
            msg_date = msg.date.astimezone(timezone.utc)
            if msg_date < cutoff:
                break  # newest-first, so everything after this is older too
            db.upsert_message(
                channel_id=channel_id,
                message_id=msg.id,
                text=msg.text,
                date=msg.date.isoformat(),
                run_id=run_id,
            )
            count += 1
            if count >= MAX_MESSAGES_PER_CHANNEL:
                break

    except FloodWaitError as e:
        logger.warning("FloodWait for %s — sleeping %ds then retrying once", username, e.seconds)
        await asyncio.sleep(e.seconds)
        async for msg in client.iter_messages(username, limit=ITERATION_LIMIT_PER_CHANNEL):
            if not msg.text or msg.date is None:
                continue
            if msg.date.astimezone(timezone.utc) < cutoff:
                break
            db.upsert_message(channel_id, msg.id, msg.text, msg.date.isoformat(), run_id)
            count += 1
            if count >= MAX_MESSAGES_PER_CHANNEL:
                break

    logger.info("Channel %s: %d messages stored", username, count)
    return count


async def _fetch_all(
    run_id: int,
    progress_cb=None,
) -> tuple[list[dict], list[str]]:
    if not _TELETHON_AVAILABLE:
        raise RuntimeError("telethon is not installed — run: pip install telethon")

    if not Path(SESSION_PATH).exists():
        raise NotAuthenticatedError(
            "Userbot not authenticated — send /auth to the bot to set up the session."
        )

    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_MESSAGE_AGE_DAYS)
    unavailable: list[str] = []

    client = TelegramClient(SESSION_PATH, settings.api_id, settings.api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        raise NotAuthenticatedError(
            "Userbot session is invalid or expired — send /auth to the bot to re-authenticate."
        )

    try:
        me = await client.get_me()
        if getattr(me, "bot", False):
            raise NotAuthenticatedError(
                "Userbot session is logged in as a bot account. Send /auth and log in "
                "with a real Telegram user phone number, not the BotFather bot token."
            )

        for ch in settings.channels:
            label = ch.display_name or ch.username
            try:
                count = await _fetch_channel(client, ch.username, run_id, cutoff)
                msg = (
                    f"  ✅ {label}: {count} recent post{'s' if count != 1 else ''}"
                    if count > 0
                    else f"  ⚠️ {label}: no text posts in the last {MAX_MESSAGE_AGE_DAYS} days"
                )
                if progress_cb:
                    progress_cb(msg)
            except Exception as exc:
                hint = _error_hint(exc)
                logger.error("Cannot fetch %s: %s", ch.username, exc)
                unavailable.append(ch.username)
                if progress_cb:
                    progress_cb(f"  ❌ {label}: {hint}")
    finally:
        await client.disconnect()

    raw = db.get_messages_for_run(run_id)
    processed: list[dict] = []
    for row in raw:
        norm_text, segments = normalize(row["message_text"] or "")
        processed.append({
            "channel_username": row["channel_username"],
            "normalized_text": norm_text,
            "segments": segments,
            "message_date": row["message_date"],
        })

    logger.info("Fetched %d messages across %d channels", len(processed), len(settings.channels))
    return processed, unavailable


def fetch_messages(run_id: int, progress_cb=None) -> tuple[list[dict], list[str]]:
    """Sync entry point for the pipeline."""
    return asyncio.run(_fetch_all(run_id, progress_cb))
