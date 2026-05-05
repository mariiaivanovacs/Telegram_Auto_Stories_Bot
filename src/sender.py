"""
Telegram delivery:
  - Bot API (httpx, synchronous) → text messages + photos to all admins
  - Telethon userbot (async)     → story posting; falls back to photos if unsupported
"""
import asyncio
import logging
from pathlib import Path

import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)

_BOT_BASE = "https://api.telegram.org/bot{token}/{method}"


# ── Bot API helpers ────────────────────────────────────────────────────────────

def _api(token: str, method: str, **kwargs) -> dict:
    url = _BOT_BASE.format(token=token, method=method)
    try:
        resp = httpx.post(url, timeout=30, **kwargs)
        return resp.json()
    except Exception as e:
        logger.error("Bot API %s error: %s", method, e)
        return {"ok": False, "description": str(e)}


def _send_text(token: str, chat_id: int, text: str, reply_markup: dict | None = None) -> bool:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    result = _api(token, "sendMessage", json=payload)
    if not result.get("ok"):
        logger.error("sendMessage to %s failed: %s", chat_id, result.get("description"))
    return bool(result.get("ok"))


def _send_photo(token: str, chat_id: int, photo_path: str) -> bool:
    try:
        with open(photo_path, "rb") as f:
            result = _api(token, "sendPhoto",
                          data={"chat_id": chat_id},
                          files={"photo": ("story.png", f, "image/png")})
    except FileNotFoundError:
        logger.error("Photo file not found: %s", photo_path)
        return False
    if not result.get("ok"):
        logger.error("sendPhoto %s to %s failed: %s",
                     photo_path, chat_id, result.get("description"))
    return bool(result.get("ok"))


def send_photo_to_chat(chat_id: int, photo_path: str) -> bool:
    """Send one local PNG/JPEG image to a specific chat."""
    settings = get_settings()
    return _send_photo(settings.bot_token, chat_id, photo_path)


# ── Userbot story posting ──────────────────────────────────────────────────────

async def _post_stories_userbot(story_paths: list[str]) -> bool:
    """
    Post images as Telegram Stories via the userbot session.
    Returns True if at least one story was posted.
    """
    settings = get_settings()
    session = "data/userbot.session"

    if not Path(session).exists():
        logger.warning("Userbot session not found at %s — skipping story posting", session)
        return False

    try:
        from telethon import TelegramClient
        from telethon.tl.functions.stories import SendStoryRequest
        from telethon.tl.types import InputMediaUploadedPhoto, InputPeerSelf
    except ImportError as e:
        logger.warning("Telethon story imports unavailable: %s", e)
        return False

    posted = 0
    try:
        async with TelegramClient(session, settings.api_id, settings.api_hash) as client:
            for path in story_paths:
                try:
                    uploaded = await client.upload_file(path)
                    await client(SendStoryRequest(
                        peer=InputPeerSelf(),
                        media=InputMediaUploadedPhoto(file=uploaded),
                        caption="",
                        period=86400,  # 24 hours
                    ))
                    posted += 1
                    logger.info("Story posted via userbot: %s", path)
                except Exception as e:
                    logger.error("Failed to post story %s: %s", path, e)
    except Exception as e:
        logger.error("Userbot session error during story posting: %s", e)
        return False

    return posted > 0


def post_stories_userbot(story_paths: list[str]) -> bool:
    return asyncio.run(_post_stories_userbot(story_paths))


# ── Public delivery API ────────────────────────────────────────────────────────

def send_all(
    price_list_text: str,
    report_text: str,
    story_paths: list[str],
) -> list[str]:
    """
    Deliver the full run results to all admins.
    Returns a list of error strings (empty = all delivered successfully).
    """
    settings = get_settings()
    token = settings.bot_token
    admin_ids = [a.telegram_id for a in settings.admins]
    errors: list[str] = []

    for admin_id in admin_ids:
        if not _send_text(token, admin_id, price_list_text):
            errors.append(f"Price list not delivered to {admin_id}")

        if not _send_text(token, admin_id, report_text):
            errors.append(f"Report not delivered to {admin_id}")

        for path in story_paths:
            if not _send_photo(token, admin_id, path):
                errors.append(f"Photo {Path(path).name} not delivered to {admin_id}")

    # Try posting as Telegram Stories via userbot
    # if story_paths:
    #     ok = post_stories_userbot(story_paths)
    #     if not ok:
    #         logger.info("Userbot story posting skipped/failed — images sent as photos above")

    return errors


def send_to_chat(chat_id: int, text: str) -> None:
    """Send a plain message to a specific chat (sync, uses httpx)."""
    settings = get_settings()
    _send_text(settings.bot_token, chat_id, text)


def send_to_chat_markup(chat_id: int, text: str, reply_markup: dict) -> None:
    """Send a message with an inline keyboard to a specific chat."""
    settings = get_settings()
    _send_text(settings.bot_token, chat_id, text, reply_markup=reply_markup)


def send_to_admins(text: str) -> None:
    """Send a plain message to all admins (no alert prefix)."""
    settings = get_settings()
    for a in settings.admins:
        _send_text(settings.bot_token, a.telegram_id, text)


def notify_admin(text: str) -> None:
    """Send an urgent alert (⚠️ prefix) to all admins."""
    send_to_admins(f"⚠️ {text}")
