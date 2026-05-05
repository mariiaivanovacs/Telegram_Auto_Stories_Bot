"""
Long-running admin Telegram bot.
Handles commands and the inline "Run Scraper Now" trigger button.
The daily pipeline is scheduled via AsyncIOScheduler (no system cron needed).
"""
import asyncio
import logging
import re
from pathlib import Path

import pytz
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except Exception:  # optional dependency for scheduled runs
    AsyncIOScheduler = None

try:
    from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ConversationHandler,
        MessageHandler,
        ContextTypes,
        filters,
    )
    from telegram.error import Conflict
except Exception:  # telegram is an optional runtime dependency for the bot
    BotCommand = InlineKeyboardButton = InlineKeyboardMarkup = Update = None
    Application = CallbackQueryHandler = CommandHandler = ContextTypes = None
    ConversationHandler = MessageHandler = filters = None
    Conflict = Exception

import src.db as db
import src.lock as lock
from src.config import get_settings
from src.main import setup_logging
from src.sender import send_to_admins, send_to_chat, send_to_chat_markup

logger = logging.getLogger(__name__)


# ── Auth guard ─────────────────────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    try:
        return db.is_admin(user_id)
    except Exception as exc:
        logger.error("Admin check failed for user %d: %s", user_id, exc)
        return False


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_ping(update, _context) -> None:
    await update.message.reply_text("pong")


async def cmd_start(update, _context) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return

    last = db.get_last_run()
    if last:
        ts = last["started_at"][:16].replace("T", " ")
        icon = "✅" if last["status"] == "success" else "⚠️"
        status_line = f"Last run: {ts} {icon} ({last['status']})"
    else:
        status_line = "No runs yet"

    keyboard = [
        [InlineKeyboardButton("Step 1: Fetch", callback_data="run_step_1")],
        [InlineKeyboardButton("Step 2: Match + Prices", callback_data="run_step_2")],
        [InlineKeyboardButton("Admin Panel", callback_data="admin_panel")],
        [InlineKeyboardButton("Run Full Pipeline", callback_data="run_now")],
    ]
    await update.message.reply_text(
        f"Admin panel\n{status_line}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_run(update, context) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    await _trigger(update, context)


async def cmd_run_step_1(update, _context) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return

    if lock.is_locked():
        await update.message.reply_text("⚠️ A run is already in progress.")
        return

    await update.message.reply_text("⏳ Step 1: fetching channel messages...")
    await asyncio.to_thread(_run_step_1_sync, update.effective_chat.id)


async def cmd_run_step_2(update, _context) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return

    if lock.is_locked():
        await update.message.reply_text("⚠️ A run is already in progress.")
        return

    await update.message.reply_text("⏳ Step 2: fetching, matching products, and calculating prices...")
    await asyncio.to_thread(_run_step_2_sync, update.effective_chat.id)


async def cmd_admin(update, _context) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    db.init(get_settings())
    await update.message.reply_text(_admin_panel_text(), reply_markup=_admin_panel_keyboard())


async def cmd_discount(update, _context) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    db.init(get_settings())
    settings = get_settings()
    discount = db.get_pricing_discount(settings.pricing.discount)
    await update.message.reply_text(
        f"Current competitor discount: {_format_money(discount)}\n"
        "Use /set_discount 500 or /set_discount 1000 for manual values."
    )


async def cmd_set_discount(update, context) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return
    db.init(get_settings())
    if not context.args:
        await update.message.reply_text("Usage: /set_discount <rubles>, for example /set_discount 1000")
        return
    try:
        discount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid discount. Use a number, for example /set_discount 500")
        return
    if discount < 0 or discount > 100_000:
        await update.message.reply_text("Discount should be between 0 and 100000 RUB.")
        return
    db.set_pricing_discount(discount)
    await update.message.reply_text(f"Discount updated: {_format_money(discount)}")


async def cmd_status(update, _context) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return

    run = db.get_last_run()
    if not run:
        await update.message.reply_text("No completed runs yet.")
        return

    ts = run["started_at"][:16].replace("T", " ")
    icon = "✅" if run["status"] == "success" else ("⚠️" if run["status"] == "partial" else "❌")
    total = run["products_found"] + run["products_missing"]
    await update.message.reply_text(
        f"{icon} Last run: {ts}\n"
        f"Status: {run['status']}\n"
        f"Found: {run['products_found']} / {total}\n"
        f"Missing: {run['products_missing']}"
    )


async def cmd_prices(update, _context) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return

    db.init(get_settings())
    await update.message.reply_text(_stored_prices_text())


async def cmd_add_admin(update, context) -> None:
    caller = update.effective_user.id
    if not _is_admin(caller):
        await update.message.reply_text("Not authorized.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /add_admin <telegram_user_id> [@username]")
        return

    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID — must be a number.")
        return

    username = context.args[1] if len(context.args) > 1 else ""
    added = db.add_admin(new_id, username, added_by=caller)

    if added:
        await update.message.reply_text(f"✅ Admin {new_id} added.")
        logger.info("Admin %d added by %d", new_id, caller)
    else:
        await update.message.reply_text(f"ℹ️ {new_id} is already an admin.")


# ── Trigger button callback ────────────────────────────────────────────────────

async def btn_run_now(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    await _trigger(update, context, from_button=True)


async def btn_run_step_1(update, _context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    if lock.is_locked():
        await query.edit_message_text("⚠️ A run is already in progress.")
        return
    await query.edit_message_text("⏳ Step 1: fetching channel messages...")
    await asyncio.to_thread(_run_step_1_sync, update.effective_chat.id)


async def btn_run_step_2(update, _context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    if lock.is_locked():
        await query.edit_message_text("⚠️ A run is already in progress.")
        return
    await query.edit_message_text("⏳ Step 2: fetching, matching products, and calculating prices...")
    await asyncio.to_thread(_run_step_2_sync, update.effective_chat.id)


async def btn_admin_panel(update, _context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    db.init(get_settings())
    await query.edit_message_text(_admin_panel_text(), reply_markup=_admin_panel_keyboard())


async def btn_discount(update, _context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    db.init(get_settings())
    raw = query.data.rsplit("_", 1)[-1]
    discount = int(raw)
    db.set_pricing_discount(discount)
    await query.edit_message_text(
        f"Discount updated: {_format_money(discount)}\n\n{_admin_panel_text()}",
        reply_markup=_admin_panel_keyboard(),
    )


async def btn_show_prices(update, _context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    db.init(get_settings())
    await query.edit_message_text(_stored_prices_text(), reply_markup=_admin_panel_keyboard())


async def btn_approve_price(update, _context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return

    change_id = int(query.data.rsplit("_", 1)[-1])
    change = db.get_pending_price_change(change_id)
    if not change or change["status"] != "pending":
        await query.edit_message_text("This price change is no longer pending.")
        return

    db.update_product_price(change["product_id"], change["proposed_price"])
    db.resolve_pending_price_change(change_id, "approved", update.effective_user.id)
    await query.edit_message_text(
        f"Approved: {change['canonical_name']}\n"
        f"Stored price updated to {_format_money(change['proposed_price'])}."
    )


async def btn_manual_price(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return

    change_id = int(query.data.rsplit("_", 1)[-1])
    change = db.get_pending_price_change(change_id)
    if not change or change["status"] != "pending":
        await query.edit_message_text("This price change is no longer pending.")
        return

    context.user_data["manual_price_change_id"] = change_id
    await query.edit_message_text(
        f"Send manual price for {change['canonical_name']} as a number, for example 99990."
    )


async def manual_price_message(update, context) -> None:
    change_id = context.user_data.get("manual_price_change_id")
    if not change_id:
        return
    if not _is_admin(update.effective_user.id):
        return

    raw = update.message.text.strip().replace(" ", "")
    try:
        manual_price = int(raw)
    except ValueError:
        await update.message.reply_text("Send only a number, for example 99990.")
        return

    if manual_price <= 0:
        await update.message.reply_text("Price must be greater than zero.")
        return

    change = db.get_pending_price_change(change_id)
    if not change or change["status"] != "pending":
        context.user_data.pop("manual_price_change_id", None)
        await update.message.reply_text("This price change is no longer pending.")
        return

    db.update_product_price(change["product_id"], manual_price)
    db.resolve_pending_price_change(
        change_id,
        "manual",
        update.effective_user.id,
        manual_price=manual_price,
    )
    context.user_data.pop("manual_price_change_id", None)
    await update.message.reply_text(
        f"Manual price saved for {change['canonical_name']}: {_format_money(manual_price)}"
    )


async def _trigger(
    update,
    _context,
    from_button: bool = False,
) -> None:
    if lock.is_locked():
        msg = "⚠️ A run is already in progress."
        if from_button:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    if from_button:
        await update.callback_query.edit_message_text("⏳ Starting pipeline...")
    else:
        await update.message.reply_text("⏳ Starting pipeline...")

    chat_id = update.effective_chat.id

    def progress(msg: str) -> None:
        send_to_chat(chat_id, msg)

    await asyncio.to_thread(_run_pipeline_sync, progress)


# ── Pipeline runner (sync, called from thread) ─────────────────────────────────

def _run_pipeline_sync(progress_cb=None) -> None:
    try:
        from src.main import run_pipeline
        run_pipeline(progress_cb=progress_cb)
    except Exception as exc:
        logger.error("Pipeline error: %s", exc, exc_info=True)


def _admin_panel_text() -> str:
    settings = get_settings()
    discount = db.get_pricing_discount(settings.pricing.discount)
    return (
        "Admin panel\n"
        f"Competitor discount: {_format_money(discount)}\n"
        "Price rule: minimum competitor price minus discount.\n"
        "Manual value: /set_discount <rubles>\n"
        "View stored prices: /prices"
    )


def _admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("-500 RUB", callback_data="discount_500"),
            InlineKeyboardButton("-1000 RUB", callback_data="discount_1000"),
        ],
        [
            InlineKeyboardButton("Step 2 Preview", callback_data="run_step_2"),
            InlineKeyboardButton("Stored Prices", callback_data="show_prices"),
        ],
    ])


def _stored_prices_text() -> str:
    products = db.get_all_products()
    if not products:
        return "No products in database."

    lines = ["Current stored prices:"]
    for p in products:
        lines.append(f"- {p['canonical_name']}: {_format_money(p['current_price'])}")
    return "\n".join(lines)


def _message_chunks(text: str, limit: int = 3500) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if current and len(current) + len(line) > limit:
            chunks.append(current.rstrip())
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit].rstrip())
            line = line[limit:]
        current += line
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def _format_step_1_messages(run_id: int, unavailable: list[str]) -> list[str]:
    rows = db.get_messages_for_run(run_id)
    if not rows:
        lines = ["Step 1 complete: no messages were fetched for today."]
        if unavailable:
            lines.append("Unavailable channels: " + ", ".join(unavailable))
        return ["\n".join(lines)]

    header = [
        f"Step 1 complete: fetched {len(rows)} message{'s' if len(rows) != 1 else ''}.",
    ]
    if unavailable:
        header.append("Unavailable channels: " + ", ".join(unavailable))

    blocks = ["\n".join(header)]
    for idx, row in enumerate(rows, start=1):
        text = (row["message_text"] or "").strip() or "[empty text]"
        blocks.append(
            f"{idx}. @{row['channel_username']} | message #{row['message_id']} | {row['message_date']}\n"
            f"{text}"
        )

    return _message_chunks("\n\n".join(blocks))


def _format_money(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}".replace(",", " ") + " RUB"


def _format_delta(value: int | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,}".replace(",", " ") + " RUB"


def _format_step_2_results(
    run_id: int,
    unavailable: list[str],
    price_results: list[dict],
    match_results: dict,
    discount: int,
) -> list[str]:
    message_count = len(db.get_messages_for_run(run_id))
    found = [r for r in price_results if not r["price_kept"]]
    missing = [r for r in price_results if r["price_kept"]]

    lines = [
        f"Step 2 complete: fetched {message_count} message{'s' if message_count != 1 else ''}.",
        f"Matched products: {len(found)}/{len(price_results)}",
        f"Discount: {_format_money(discount)}",
        "Mode: normal changes are saved; large changes require confirmation.",
    ]
    if unavailable:
        lines.append("Unavailable channels: " + ", ".join(unavailable))

    line_calculations = _format_matched_line_calculations(match_results, discount)
    if line_calculations:
        lines.append("")
        lines.append("Message text -> extracted price -> calculated new price:")
        lines.extend(line_calculations)

    if found:
        lines.append("")
        lines.append("Matched and calculated:")
        for r in found:
            all_prices = match_results.get(r["template_key"], {}).get("all_prices", [])
            seen_prices = ", ".join(_format_money(p) for p in all_prices)
            line = (
                f"- {r['canonical_name']}: minimum competitor {_format_money(r['competitor_price'])}"
                f" -> calculated {_format_money(r['calculated_price'])}"
                f" (old {_format_money(r['old_price'])}, delta {_format_delta(r['price_delta'])})"
            )
            if r["is_large_change"]:
                line += " LARGE CHANGE"
            if seen_prices and seen_prices != _format_money(r["competitor_price"]):
                line += f"; seen: {seen_prices}"
            lines.append(line)

    if missing:
        lines.append("")
        lines.append("No match found:")
        for r in missing:
            lines.append(f"- {r['canonical_name']} (keeping {_format_money(r['old_price'])})")

    return _message_chunks("\n".join(lines))


def _format_matched_line_calculations(match_results: dict, discount: int) -> list[str]:
    lines: list[str] = []
    for product_id, match in match_results.items():
        matched_lines = match.get("matched_lines") or []
        if not matched_lines:
            continue
        lines.append(product_id)
        for item in matched_lines:
            price = item["price"]
            text = item["text"]
            lines.append(
                f"  @{item['channel']}: {text} -> {_format_money(price)} -> {_format_money(price - discount)}"
            )
    return lines


def _format_iphone_debug_lines(run_id: int) -> list[str]:
    from src.matcher import _extract_price
    from src.parser import normalize

    debug: list[str] = []
    for row in db.get_messages_for_run(run_id):
        raw_text = row["message_text"] or ""
        _norm_text, segments = normalize(raw_text)
        iphone_segments = [
            seg for seg in segments
            if "iphone" in seg and _looks_like_price_line(seg)
        ]
        if not iphone_segments:
            continue

        debug.append(f"@{row['channel_username']} #{row['message_id']}")
        for seg in iphone_segments[:20]:
            price = _extract_price(seg)
            debug.append(f"  - {seg} -> {_format_money(price)}")

    return debug


def _looks_like_price_line(segment: str) -> bool:
    return any(marker in segment for marker in ("-", "—", "–", ":")) or "₽" in segment or "rub" in segment


def _run_step_1_sync(chat_id: int) -> None:
    if not lock.acquire():
        send_to_chat(chat_id, "⚠️ A run is already in progress.")
        return

    try:
        from src.fetcher import NotAuthenticatedError, fetch_messages

        settings = get_settings()
        db.init(settings)
        run_id = db.create_run()

        def progress(msg: str) -> None:
            send_to_chat(chat_id, msg)

        try:
            _processed, unavailable = fetch_messages(run_id, progress_cb=progress)
            rows = db.get_messages_for_run(run_id)
            db.finish_run(
                run_id,
                "step_1",
                len(rows),
                0,
                [f"Channel unavailable: {ch}" for ch in unavailable],
            )
            for chunk in _format_step_1_messages(run_id, unavailable):
                send_to_chat(chat_id, chunk)
        except NotAuthenticatedError as exc:
            db.finish_run(run_id, "failed", 0, 0, [str(exc)])
            send_to_chat(chat_id, f"🔐 {exc}\nUse /auth in this chat to authenticate the userbot.")
        except Exception as exc:
            logger.error("Step 1 fetch error: %s", exc, exc_info=True)
            db.finish_run(run_id, "failed", 0, 0, [str(exc)])
            send_to_chat(chat_id, f"❌ Step 1 failed: {exc}")
    finally:
        lock.release()


def _run_step_2_sync(chat_id: int) -> None:
    if not lock.acquire():
        send_to_chat(chat_id, "⚠️ A run is already in progress.")
        return

    try:
        from src.fetcher import NotAuthenticatedError, fetch_messages
        from src.matcher import match_products
        from src.pricing import calculate_prices

        settings = get_settings()
        db.init(settings)
        run_id = db.create_run()

        def progress(msg: str) -> None:
            send_to_chat(chat_id, msg)

        try:
            messages, unavailable = fetch_messages(run_id, progress_cb=progress)
            progress(f"📥 Step 1 done: {len(messages)} normalized message{'s' if len(messages) != 1 else ''}.")

            match_results = match_products(messages, settings.products)
            found = sum(1 for v in match_results.values() if v["min_price"] is not None)
            progress(f"🔎 Step 2 match: {found}/{len(settings.products)} products found.")
            discount = db.get_pricing_discount(settings.pricing.discount)

            price_results = calculate_prices(
                match_results,
                db.get_all_products(),
                discount=discount,
                large_change_threshold=settings.pricing.large_change_threshold,
            )

            n_priced = sum(1 for r in price_results if not r["price_kept"])
            n_missing = sum(1 for r in price_results if r["price_kept"])
            for r in price_results:
                if not r["price_kept"] and not r["is_large_change"]:
                    db.update_product_price(r["db_id"], r["calculated_price"])

            db.finish_run(
                run_id,
                "step_2",
                n_priced,
                n_missing,
                [f"Channel unavailable: {ch}" for ch in unavailable],
            )
            for chunk in _format_step_2_results(run_id, unavailable, price_results, match_results, discount):
                send_to_chat(chat_id, chunk)
            _send_large_change_approvals(chat_id, run_id, price_results)
        except NotAuthenticatedError as exc:
            db.finish_run(run_id, "failed", 0, 0, [str(exc)])
            send_to_chat(chat_id, f"🔐 {exc}\nUse /auth in this chat to authenticate the userbot.")
        except Exception as exc:
            logger.error("Step 2 error: %s", exc, exc_info=True)
            db.finish_run(run_id, "failed", 0, 0, [str(exc)])
            send_to_chat(chat_id, f"❌ Step 2 failed: {exc}")
    finally:
        lock.release()


def _send_large_change_approvals(chat_id: int, run_id: int, price_results: list[dict]) -> None:
    for result in price_results:
        if result["price_kept"] or not result["is_large_change"]:
            continue

        change_id = db.create_pending_price_change(
            run_id=run_id,
            product_id=result["db_id"],
            proposed_price=result["calculated_price"],
            old_price=result["old_price"],
        )
        text = (
            "Large price change needs confirmation\n"
            f"{result['canonical_name']}\n"
            f"Old: {_format_money(result['old_price'])}\n"
            f"New: {_format_money(result['calculated_price'])}\n"
            f"Delta: {_format_delta(result['price_delta'])}"
        )
        reply_markup = {
            "inline_keyboard": [[
                {"text": "ДА", "callback_data": f"approve_price_{change_id}"},
                {"text": "написать свою цену", "callback_data": f"manual_price_{change_id}"},
            ]]
        }
        send_to_chat_markup(chat_id, text, reply_markup)


# ── Scheduled daily run ────────────────────────────────────────────────────────

async def _scheduled_run() -> None:
    logger.info("Scheduled daily run triggered by APScheduler")

    def progress(msg: str) -> None:
        send_to_admins(msg)

    await asyncio.to_thread(_run_pipeline_sync, progress)


# ── Scheduler lifecycle ────────────────────────────────────────────────────────

async def _post_init(application: Application) -> None:
    settings = get_settings()
    db.init(settings)
    await application.bot.set_my_commands([
        BotCommand("start", "Open admin panel"),
        BotCommand("admin", "Manage discount and quick actions"),
        BotCommand("run_step_1", "Fetch recent channel messages"),
        BotCommand("run_step_2", "Fetch, match, and preview prices"),
        BotCommand("run", "Run the full pipeline"),
        BotCommand("prices", "View current stored prices"),
        BotCommand("discount", "View competitor discount"),
        BotCommand("set_discount", "Set manual discount in RUB"),
        BotCommand("status", "Show last run status"),
        BotCommand("auth", "Authenticate Telegram userbot"),
        BotCommand("add_admin", "Add another admin"),
        BotCommand("cancel", "Cancel authentication"),
    ])
    tz = pytz.timezone(settings.schedule.timezone)
    hour, minute = map(int, settings.schedule.run_time.split(":"))

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(_scheduled_run, trigger="cron", hour=hour, minute=minute)
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info(
        "Scheduler started: daily run at %s %s",
        settings.schedule.run_time,
        settings.schedule.timezone,
    )


async def _post_shutdown(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)


# ── Userbot auth flow ──────────────────────────────────────────────────────────
# States for the /auth ConversationHandler
_AUTH_PHONE, _AUTH_CODE, _AUTH_PASSWORD = range(3)


async def _disconnect_auth_client(context) -> None:
    client = context.user_data.get("auth_client")
    if client:
        try:
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auth client disconnect failed: %s", exc)


def _remove_session_file(session_path: str) -> None:
    path = Path(session_path)
    for candidate in (path, path.with_name(f"{path.name}-journal")):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def _extract_login_code(text: str) -> str:
    return "".join(re.findall(r"\d", text))


async def cmd_auth(update, context) -> int:
    """Start the Telethon userbot authentication flow."""
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Not authorized.")
        return ConversationHandler.END

    try:
        from telethon import TelegramClient
        from src.fetcher import SESSION_PATH
    except ImportError:
        await update.message.reply_text("❌ telethon not installed — run: pip install telethon")
        return ConversationHandler.END

    settings = get_settings()
    await _disconnect_auth_client(context)
    context.user_data.clear()

    client = TelegramClient(SESSION_PATH, settings.api_id, settings.api_hash)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        await client.disconnect()
        if getattr(me, "bot", False):
            _remove_session_file(SESSION_PATH)
            client = TelegramClient(SESSION_PATH, settings.api_id, settings.api_hash)
            await client.connect()
            await update.message.reply_text(
                "⚠️ The saved session was a Telegram bot account, which cannot read "
                "channel history. I reset it.\n\n"
                "📱 Send your real Telegram user phone number (e.g. +79123456789):\n\n"
                "Send /cancel to abort."
            )
            context.user_data["auth_client"] = client
            return _AUTH_PHONE

        await update.message.reply_text(
            f"✅ Userbot is already authenticated as {me.first_name or 'Telegram user'}."
        )
        return ConversationHandler.END

    context.user_data["auth_client"] = client
    await update.message.reply_text(
        "📱 Send your phone number (e.g. +79123456789):\n\n"
        "Send /cancel to abort."
    )
    return _AUTH_PHONE


async def _auth_phone(update, context) -> int:
    phone = update.message.text.strip()
    client = context.user_data.get("auth_client")
    if not client:
        await update.message.reply_text("❌ Session expired. Use /auth to start again.")
        return ConversationHandler.END

    try:
        result = await client.send_code_request(phone)
        context.user_data["auth_phone"] = phone
        context.user_data["auth_hash"] = result.phone_code_hash
        await update.message.reply_text(
            "📲 Code sent! Enter the newest code you received from Telegram."
        )
        return _AUTH_CODE
    except Exception as exc:
        logger.error("send_code_request failed: %s", exc)
        await update.message.reply_text(f"❌ Error: {exc}\nUse /auth to try again.")
        await client.disconnect()
        context.user_data.clear()
        return ConversationHandler.END


async def _auth_code(update, context) -> int:
    code = _extract_login_code(update.message.text)
    client = context.user_data.get("auth_client")
    phone = context.user_data.get("auth_phone")
    phone_hash = context.user_data.get("auth_hash")

    if not code:
        await update.message.reply_text("❌ I could not find digits in that message. Send only the login code.")
        return _AUTH_CODE

    if not (client and phone and phone_hash):
        await update.message.reply_text("❌ Session expired. Use /auth to start again.")
        return ConversationHandler.END

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_hash)
        me = await client.get_me()
        if getattr(me, "bot", False):
            await client.disconnect()
            _remove_session_file("data/userbot.session")
            context.user_data.clear()
            await update.message.reply_text(
                "❌ This login produced a bot session. Use /auth again and enter "
                "a real Telegram user phone number, not the BotFather bot token."
            )
            return ConversationHandler.END
        await client.disconnect()
        context.user_data.clear()
        await update.message.reply_text(
            "✅ Userbot authenticated! Session saved.\n"
            "You can now run /run to start the pipeline."
        )
        return ConversationHandler.END
    except Exception as exc:  # noqa: BLE001 — check by name for optional dep
        if type(exc).__name__ == "SessionPasswordNeededError":
            context.user_data["auth_needs_password"] = True
            await update.message.reply_text(
                "🔐 2FA is enabled. Enter your Telegram cloud password:"
            )
            return _AUTH_PASSWORD
        if type(exc).__name__ == "PhoneCodeInvalidError":
            logger.warning("Invalid Telegram login code entered")
            await update.message.reply_text(
                "❌ That code was not accepted. Enter the newest Telegram login code again."
            )
            return _AUTH_CODE
        if type(exc).__name__ == "PhoneCodeExpiredError":
            logger.warning("Telegram login code expired")
            await update.message.reply_text(
                "❌ Telegram says this code is expired. Use /auth again and enter only "
                "the newest code from the latest Telegram message."
            )
            await client.disconnect()
            context.user_data.clear()
            return ConversationHandler.END
        logger.error("sign_in failed: %s", exc)
        await update.message.reply_text(f"❌ Wrong code: {exc}\nUse /auth to try again.")
        await client.disconnect()
        context.user_data.clear()
        return ConversationHandler.END


async def _auth_password(update, context) -> int:
    password = update.message.text.strip()
    client = context.user_data.get("auth_client")

    if not client or not context.user_data.get("auth_needs_password"):
        await update.message.reply_text("❌ Session expired. Use /auth to start again.")
        return ConversationHandler.END

    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        if getattr(me, "bot", False):
            await client.disconnect()
            _remove_session_file("data/userbot.session")
            context.user_data.clear()
            await update.message.reply_text(
                "❌ This login produced a bot session. Use /auth again and enter "
                "a real Telegram user phone number, not the BotFather bot token."
            )
            return ConversationHandler.END
        await client.disconnect()
        context.user_data.clear()
        await update.message.reply_text(
            f"✅ Authenticated with 2FA as {me.first_name or 'Telegram user'}! Session saved.\n"
            "You can now run /run to start the pipeline."
        )
        return ConversationHandler.END
    except Exception as exc:
        logger.error("2FA sign_in failed: %s", exc)
        await update.message.reply_text(f"❌ Wrong password: {exc}\nUse /auth to try again.")
        await client.disconnect()
        context.user_data.clear()
        return ConversationHandler.END


async def _auth_cancel(update, context) -> int:
    client = context.user_data.get("auth_client")
    if client:
        await client.disconnect()
    context.user_data.clear()
    await update.message.reply_text("Auth cancelled.")
    return ConversationHandler.END


# ── Entry point ────────────────────────────────────────────────────────────────

def run_bot() -> None:
    setup_logging()
    settings = get_settings()
    if not settings.bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set — admin bot will not start")
        return

    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    auth_conv = ConversationHandler(
        entry_points=[CommandHandler("auth", cmd_auth)],
        states={
            _AUTH_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, _auth_phone)],
            _AUTH_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, _auth_code)],
            _AUTH_PASSWORD: [MessageHandler(filters.TEXT & ~filters.Regex(r"^/cancel$"), _auth_password)],
        },
        fallbacks=[CommandHandler("cancel", _auth_cancel)],
    )

    app.add_handler(auth_conv)
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("run_step_1", cmd_run_step_1))
    app.add_handler(CommandHandler("run_step_2", cmd_run_step_2))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("prices", cmd_prices))
    app.add_handler(CommandHandler("discount", cmd_discount))
    app.add_handler(CommandHandler("set_discount", cmd_set_discount))
    app.add_handler(CommandHandler("add_admin", cmd_add_admin))
    app.add_handler(CallbackQueryHandler(btn_run_step_1, pattern="^run_step_1$"))
    app.add_handler(CallbackQueryHandler(btn_run_step_2, pattern="^run_step_2$"))
    app.add_handler(CallbackQueryHandler(btn_admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(btn_discount, pattern="^discount_(500|1000)$"))
    app.add_handler(CallbackQueryHandler(btn_show_prices, pattern="^show_prices$"))
    app.add_handler(CallbackQueryHandler(btn_approve_price, pattern="^approve_price_\\d+$"))
    app.add_handler(CallbackQueryHandler(btn_manual_price, pattern="^manual_price_\\d+$"))
    app.add_handler(CallbackQueryHandler(btn_run_now, pattern="^run_now$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manual_price_message))

    logger.info("Admin bot polling started")
    try:
        app.run_polling(drop_pending_updates=True)
    except Conflict:
        logger.error(
            "\n\n"
            "CONFLICT — another bot instance is already running.\n"
            "Only one instance can poll Telegram at a time.\n\n"
            "  Stop Docker:    docker compose down\n"
            "  Kill terminal:  find and kill the other 'python -m src.bot' process\n\n"
            "Then retry: python -m src.bot\n"
        )


if __name__ == "__main__":
    run_bot()
