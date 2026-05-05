"""
One-time interactive Telethon session setup.
Run this once on the server before starting Docker.
Saves the session to data/userbot.session.
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from src.config import get_settings

SESSION_PATH = "data/userbot.session"


def _extract_login_code(text: str) -> str:
    return "".join(re.findall(r"\d", text))


def _remove_session_file() -> None:
    path = Path(SESSION_PATH)
    for candidate in (path, path.with_name(f"{path.name}-journal")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


async def main():
    settings = get_settings()

    if not settings.api_id or not settings.api_hash:
        print("ERROR: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env")
        sys.exit(1)

    Path("data").mkdir(exist_ok=True)

    client = TelegramClient(SESSION_PATH, settings.api_id, settings.api_hash)
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            if getattr(me, "bot", False):
                print("Existing session is a bot account; replacing it with a user session.")
                await client.disconnect()
                _remove_session_file()
                client = TelegramClient(SESSION_PATH, settings.api_id, settings.api_hash)
                await client.connect()
            else:
                print(f"✓ Existing session is valid: {me.first_name} (@{me.username})")
                return

        phone = settings.phone or input("Enter your phone number (e.g. +79001234567): ")
        for attempt in range(1, 4):
            sent = await client.send_code_request(phone)
            print("A new login code was sent. Use the newest code only.")
            code = _extract_login_code(input("Enter the code you received in Telegram: "))
            if not code:
                print("No digits found in that input.")
                continue
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
                break
            except SessionPasswordNeededError:
                password = input("Two-factor password: ")
                await client.sign_in(password=password)
                break
            except Exception as exc:
                print(f"Login failed on attempt {attempt}: {exc}")
                if attempt == 3:
                    raise

        me = await client.get_me()
        if getattr(me, "bot", False):
            raise RuntimeError("Authenticated as a bot account; use a real Telegram user phone number.")
        print(f"✓ Session saved to {SESSION_PATH}")
        print(f"  Logged in as: {me.first_name} (@{me.username})")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
