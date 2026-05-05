"""
Long-running admin Telegram bot.
Handles commands and the inline "Run Scraper Now" trigger button.
The daily pipeline is scheduled via AsyncIOScheduler (no system cron needed).
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile

import pytz
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except Exception:  # optional dependency for scheduled runs
    AsyncIOScheduler = None
try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    from telegram.error import Conflict
except Exception:  # telegram is an optional runtime dependency for tests/imports
    InlineKeyboardButton = InlineKeyboardMarkup = Update = None
    Application = CallbackQueryHandler = CommandHandler = ContextTypes = None
    MessageHandler = filters = None
    Conflict = Exception

import src.db as db
import src.lock as lock
from src.config import get_settings
from src.main import setup_logging
from src.sender import send_photo_to_chat, send_to_admins, send_to_chat

logger = logging.getLogger(__name__)


# ── Auth guard ─────────────────────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    try:
        return db.is_admin(user_id)
    except Exception as exc:
        logger.error("Admin check failed for user %d: %s", user_id, exc)
        return False


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_ping(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong")


async def cmd_start(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return

    last = db.get_last_run()
    if last:
        ts = last["started_at"][:16].replace("T", " ")
        icon = "✅" if last["status"] == "success" else "⚠️"
        status_line = f"Последний запуск: {ts} {icon} ({last['status']})"
    else:
        status_line = "Запусков ещё не было"

    keyboard = [
        [InlineKeyboardButton("▶️ Полный пайплайн", callback_data="run_now")],
        [InlineKeyboardButton("Шаг 3: Сторис", callback_data="run_step_3")],
        [InlineKeyboardButton("Шаг 4: Тест шрифта", callback_data="run_step_4")],
        [InlineKeyboardButton("Управление фото", callback_data="manage_images")],
    ]
    await update.message.reply_text(
        f"Панель управления\n{status_line}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    await _trigger(update, context)


async def cmd_status(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return

    run = db.get_last_run()
    if not run:
        await update.message.reply_text("Запусков ещё не было.")
        return

    ts = run["started_at"][:16].replace("T", " ")
    icon = "✅" if run["status"] == "success" else ("⚠️" if run["status"] == "partial" else "❌")
    total = run["products_found"] + run["products_missing"]
    await update.message.reply_text(
        f"{icon} Последний запуск: {ts}\n"
        f"Статус: {run['status']}\n"
        f"Найдено: {run['products_found']} / {total}\n"
        f"Пропущено: {run['products_missing']}"
    )


async def cmd_prices(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return

    products = db.get_all_products()
    if not products:
        await update.message.reply_text("Нет товаров в базе.")
        return

    lines = ["📋 Текущие цены:"]
    for p in products:
        price = p["current_price"]
        price_str = f"{price:,}".replace(",", " ") + " ₽" if price is not None else "—"
        lines.append(f"• {p['canonical_name']}: {price_str}")

    await update.message.reply_text("\n".join(lines))


async def cmd_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller = update.effective_user.id
    if not _is_admin(caller):
        await update.message.reply_text("Нет доступа.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /add_admin <telegram_user_id> [@username]")
        return

    try:
        new_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Неверный ID — нужно число.")
        return

    username = context.args[1] if len(context.args) > 1 else ""
    added = db.add_admin(new_id, username, added_by=caller)

    if added:
        await update.message.reply_text(f"✅ Администратор {new_id} добавлен.")
        logger.info("Admin %d added by %d", new_id, caller)
    else:
        await update.message.reply_text(f"ℹ️ {new_id} уже администратор.")


async def cmd_run_step_3(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return

    if lock.is_locked():
        await update.message.reply_text("⚠️ Запуск уже выполняется.")
        return

    await update.message.reply_text("⏳ Шаг 3: парсинг → цены → сторис...")
    await asyncio.to_thread(_run_step_3_sync, update.effective_chat.id)


async def cmd_run_step_4(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return

    if lock.is_locked():
        await update.message.reply_text("⚠️ Запуск уже выполняется.")
        return

    await update.message.reply_text("⏳ Шаг 4: рендер тестовых сторис...")
    await asyncio.to_thread(_run_step_4_sync, update.effective_chat.id)


# ── Ready-image management commands ───────────────────────────────────────────

async def cmd_images(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    await update.message.reply_text(_images_text(), reply_markup=_images_keyboard())


async def cmd_delete_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /delete_image <имя или номер>")
        return

    from src.ready_images import delete_image
    name = delete_image(context.args[0])
    if name:
        await update.message.reply_text(f"✅ Удалено: {name}")
    else:
        await update.message.reply_text(
            f"Не найдено: {context.args[0]}\n"
            "Список фото: /images"
        )


async def cmd_flush_images(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return

    from src.ready_images import list_images
    count = len(list_images())
    if count == 0:
        await update.message.reply_text("Готовых фото нет.")
        return

    await update.message.reply_text(
        f"Удалить {count} фото? Это нельзя отменить.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Да, удалить", callback_data="flush_images_confirm"),
            InlineKeyboardButton("Отмена", callback_data="flush_images_cancel"),
        ]]),
    )


async def cmd_process_backgrounds(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return

    settings = get_settings()
    backgrounds_dir = getattr(settings.story, "backgrounds_dir", "backgrounds")
    await update.message.reply_text(f"⏳ Обрабатываю фото из {backgrounds_dir}/...")
    await asyncio.to_thread(_process_backgrounds_sync, update.effective_chat.id, backgrounds_dir)


# ── Photo upload handler ───────────────────────────────────────────────────────

async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.effective_user.id):
        return

    photo = update.message.photo[-1]  # highest resolution
    tg_file = await context.bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        await tg_file.download_to_drive(tmp_path)
        from src.ready_images import process_and_store
        saved = process_and_store(tmp_path)
        from pathlib import Path
        await update.message.reply_text(
            f"✅ Сохранено: {Path(saved).name}\n"
            "Список фото: /images"
        )
    except Exception as exc:
        logger.error("Photo upload processing failed: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Не удалось обработать фото: {exc}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── Trigger button callbacks ───────────────────────────────────────────────────

async def btn_run_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    await _trigger(update, context, from_button=True)


async def btn_run_step_3(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    if lock.is_locked():
        await query.edit_message_text("⚠️ Запуск уже выполняется.")
        return
    await query.edit_message_text("⏳ Шаг 3: парсинг → цены → сторис...")
    await asyncio.to_thread(_run_step_3_sync, update.effective_chat.id)


async def btn_run_step_4(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    if lock.is_locked():
        await query.edit_message_text("⚠️ Запуск уже выполняется.")
        return
    await query.edit_message_text("⏳ Шаг 4: рендер тестовых сторис...")
    await asyncio.to_thread(_run_step_4_sync, update.effective_chat.id)


async def btn_manage_images(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return
    await query.edit_message_text(_images_text(), reply_markup=_images_keyboard())


async def btn_flush_images_ask(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return

    from src.ready_images import list_images
    count = len(list_images())
    await query.edit_message_text(
        f"Удалить {count} фото? Это нельзя отменить.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Да, удалить", callback_data="flush_images_confirm"),
            InlineKeyboardButton("Отмена", callback_data="manage_images"),
        ]]),
    )


async def btn_flush_images_confirm(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return

    from src.ready_images import flush_images
    count = flush_images()
    await query.edit_message_text(f"✅ Удалено {count} фото.")


async def btn_flush_images_cancel(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отменено.")


async def btn_process_backgrounds(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(update.effective_user.id):
        return

    settings = get_settings()
    backgrounds_dir = getattr(settings.story, "backgrounds_dir", "backgrounds")
    await query.edit_message_text(f"⏳ Обрабатываю фото из {backgrounds_dir}/...")
    await asyncio.to_thread(_process_backgrounds_sync, update.effective_chat.id, backgrounds_dir)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _images_text() -> str:
    from src.ready_images import list_images
    images = list_images()
    if not images:
        return (
            "Готовых фото нет.\n\n"
            "Отправь фото в этот чат — оно будет автоматически\n"
            "обрезано, улучшено и сохранено для сторис."
        )
    lines = [f"Готовые фото ({len(images)}):"]
    for img in images:
        lines.append(f"{img['id']}. {img['name']}")
    lines += [
        "",
        "Удалить: /delete_image <имя или номер>",
        "Удалить все: /flush_images",
        "Добавить: отправь фото в этот чат",
    ]
    return "\n".join(lines)


def _images_keyboard() -> InlineKeyboardMarkup:
    from src.ready_images import list_images
    buttons = [[InlineKeyboardButton("Обработать backgrounds/", callback_data="process_backgrounds")]]
    if list_images():
        buttons.append([InlineKeyboardButton("Удалить все", callback_data="flush_images_ask")])
    return InlineKeyboardMarkup(buttons)


# ── Pipeline runners (sync, called from thread) ────────────────────────────────

async def _trigger(
    update: Update,
    _context: ContextTypes.DEFAULT_TYPE,
    from_button: bool = False,
) -> None:
    if lock.is_locked():
        msg = "⚠️ Запуск уже выполняется."
        if from_button:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    if from_button:
        await update.callback_query.edit_message_text("⏳ Запускаю пайплайн...")
    else:
        await update.message.reply_text("⏳ Запускаю пайплайн...")

    chat_id = update.effective_chat.id

    def progress(msg: str) -> None:
        send_to_chat(chat_id, msg)

    await asyncio.to_thread(_run_pipeline_sync, progress)


def _run_pipeline_sync(progress_cb=None) -> None:
    try:
        from src.main import run_pipeline
        run_pipeline(progress_cb=progress_cb)
    except Exception as exc:
        logger.error("Pipeline error: %s", exc, exc_info=True)


def _format_money(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}".replace(",", " ") + " ₽"


def _format_delta(value: int | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,}".replace(",", " ") + " ₽"


def _parse_price_input(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _format_matched_line_calculations(match_results: dict, discount: int) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for match in match_results.values():
        matched_lines = match.get("matched_lines") or []
        for item in matched_lines:
            channel = item["channel"]
            entries = grouped.setdefault(channel, [])
            text = (item.get("original_text") or item.get("text") or "").strip()
            entries.append(
                f'{len(entries) + 1}. {text} -> {_format_money(item["price"])} -> {_format_money(item["price"] - discount)}'
            )

    lines: list[str] = []
    for channel in sorted(grouped):
        lines.append(f"@{channel}")
        lines.extend(grouped[channel])
        lines.append("")
    if lines and not lines[-1].strip():
        lines.pop()
    return lines


def _format_large_change_confirmation(result: dict, match: dict) -> str:
    lines = [
        "Нужно подтверждение: большое изменение цены",
        result["canonical_name"],
        f"Канал конкурента: @{result.get('source_channel') or match.get('source_channel') or '-'}",
        f"Цена конкурента: {_format_money(result.get('competitor_price'))}",
        f"Старая: {_format_money(result.get('old_price'))}",
        f"Новая: {_format_money(result.get('calculated_price'))}",
        f"Разница: {_format_delta(result.get('price_delta'))}",
    ]
    matched_lines = match.get("matched_lines") or []
    if matched_lines:
        lines.append("")
        lines.append("Совпавшие строки:")
        for item in matched_lines[:3]:
            original = (item.get("original_text") or item.get("text") or "").strip()
            if len(original) > 180:
                original = original[:177].rstrip() + "..."
            lines.append(f'@{item["channel"]}: "{original}" -> {_format_money(item["price"])}')
    return "\n".join(lines)


def _run_step_3_sync(chat_id: int) -> None:
    if not lock.acquire():
        send_to_chat(chat_id, "⚠️ Запуск уже выполняется.")
        return

    try:
        from src.fetcher import NotAuthenticatedError, fetch_messages
        from src.matcher import match_products
        from src.pricing import calculate_prices
        from src.ready_images import pick_for_render

        settings = get_settings()
        db.init(settings)

        channels = db.get_active_channels()
        if not channels:
            send_to_chat(
                chat_id,
                "⚠️ Нет активных каналов конкурентов.\n"
                "Добавь /add_channel перед запуском.",
            )
            return

        run_id = db.create_run()

        def progress(msg: str) -> None:
            send_to_chat(chat_id, msg)

        try:
            messages, unavailable = fetch_messages(run_id, progress_cb=progress)
            progress(f"📥 Собрано {len(messages)} сообщений.")

            match_results = match_products(messages, settings.products)
            found = sum(1 for v in match_results.values() if v["min_price"] is not None)
            progress(f"🔎 Найдено {found}/{len(settings.products)} товаров.")

            discount = db.get_pricing_discount(settings.pricing.discount)
            price_results = calculate_prices(
                match_results,
                db.get_all_products(),
                discount=discount,
                large_change_threshold=settings.pricing.large_change_threshold,
            )
            for r in price_results:
                if not r["price_kept"] and not r["is_large_change"]:
                    db.update_product_price(r["db_id"], r["calculated_price"])

            ready_paths = pick_for_render()
            if ready_paths:
                progress("🎨 Рендерю сторис из готовых фото...")
                from src.story import generate_price_text_stories_from_ready
                story_paths = generate_price_text_stories_from_ready(
                    price_results, settings.story, ready_paths
                )
            else:
                progress("🎨 Готовых фото нет — рендерю из оригинальных фонов...")
                from src.story import generate_price_text_stories
                story_paths = generate_price_text_stories(price_results, settings.story)

            sent = sum(1 for p in story_paths if send_photo_to_chat(chat_id, p))
            n_priced = sum(1 for r in price_results if not r["price_kept"])
            n_missing = sum(1 for r in price_results if r["price_kept"])
            db.finish_run(
                run_id, "step_3", n_priced, n_missing,
                [f"Канал недоступен: {ch}" for ch in unavailable],
            )
            send_to_chat(chat_id, f"Шаг 3 завершён: отправлено {sent}/{len(story_paths)} сторис.")
        except NotAuthenticatedError as exc:
            db.finish_run(run_id, "failed", 0, 0, [str(exc)])
            send_to_chat(chat_id, f"🔐 {exc}\nИспользуй /auth для авторизации юзербота.")
        except Exception as exc:
            logger.error("Step 3 error: %s", exc, exc_info=True)
            db.finish_run(run_id, "failed", 0, 0, [str(exc)])
            send_to_chat(chat_id, f"❌ Шаг 3: ошибка — {exc}")
    finally:
        lock.release()


def _run_step_4_sync(chat_id: int) -> None:
    if not lock.acquire():
        send_to_chat(chat_id, "⚠️ Запуск уже выполняется.")
        return

    try:
        from src.ready_images import pick_for_render

        settings = get_settings()
        db.init(settings)
        price_results = _price_results_from_current_db()

        ready_paths = pick_for_render()
        if ready_paths:
            send_to_chat(chat_id, "🎨 Рендерю тестовые сторис из готовых фото...")
            from src.story import generate_price_text_stories_from_ready
            story_paths = generate_price_text_stories_from_ready(
                price_results,
                settings.story,
                ready_paths,
                output_dir="output/step_4_text_tests",
                font_paths=_step_4_font_variants(settings.story),
            )
        else:
            send_to_chat(chat_id, "🎨 Готовых фото нет — рендерю из оригинальных фонов...")
            from src.story import generate_price_text_stories
            story_paths = generate_price_text_stories(
                price_results,
                settings.story,
                output_dir="output/step_4_text_tests",
                font_paths=_step_4_font_variants(settings.story),
            )

        sent = sum(1 for p in story_paths if send_photo_to_chat(chat_id, p))
        send_to_chat(
            chat_id,
            f"Шаг 4 завершён: отправлено {sent}/{len(story_paths)} тестовых сторис.\n"
            "Шрифты: 1 — текущий, 2 — Apple SF UI, 3 — Avenir Next.",
        )
    except Exception as exc:
        logger.error("Step 4 text preview error: %s", exc, exc_info=True)
        send_to_chat(chat_id, f"❌ Шаг 4: ошибка — {exc}")
    finally:
        lock.release()


def _price_results_from_current_db() -> list[dict]:
    results: list[dict] = []
    for p in db.get_all_products():
        current_price = p.get("current_price")
        results.append({
            "db_id": p["id"],
            "template_key": p["template_key"],
            "canonical_name": p["canonical_name"],
            "display_name": p.get("display_name") or p["canonical_name"],
            "category": p.get("category", "Other"),
            "old_price": p.get("previous_price"),
            "default_price": p.get("default_price"),
            "competitor_price": None,
            "source_channel": None,
            "calculated_price": current_price,
            "price_delta": 0,
            "default_delta": 0,
            "is_large_change": False,
            "price_kept": current_price is None,
        })
    return results


def _step_4_font_variants(story_cfg) -> list[str | None]:
    return [
        getattr(story_cfg, "font_path", None),
        _first_existing_path([
            "/Users/mariaivanova/Library/Fonts/SF-UI-DISPLAY-SEMIBOLD.TTF",
            "/System/Library/Fonts/SFNS.ttf",
            "/System/Library/Fonts/SFCompact.ttf",
        ]),
        _first_existing_path([
            "/System/Library/Fonts/Avenir Next.ttc",
            "/System/Library/Fonts/Avenir.ttc",
            "/System/Library/Fonts/HelveticaNeue.ttc",
        ]),
    ]


def _first_existing_path(paths: list[str]) -> str | None:
    from pathlib import Path
    for path in paths:
        if Path(path).exists():
            return path
    return None


def _process_backgrounds_sync(chat_id: int, backgrounds_dir: str) -> None:
    from src.ready_images import process_backgrounds_dir
    try:
        saved, failed = process_backgrounds_dir(backgrounds_dir)
        lines = [f"✅ Обработано {len(saved)} фото → ready_images/."]
        if failed:
            lines.append(f"❌ Ошибки: {', '.join(failed)}")
        send_to_chat(chat_id, "\n".join(lines))
    except FileNotFoundError:
        send_to_chat(chat_id, f"❌ Папка не найдена: {backgrounds_dir}/")
    except Exception as exc:
        logger.error("process_backgrounds error: %s", exc, exc_info=True)
        send_to_chat(chat_id, f"❌ Ошибка: {exc}")


# ── Scheduled daily run ────────────────────────────────────────────────────────

async def _scheduled_run() -> None:
    logger.info("Scheduled daily run triggered by APScheduler")

    def progress(msg: str) -> None:
        send_to_admins(msg)

    await asyncio.to_thread(_run_pipeline_sync, progress)


# ── Scheduler lifecycle ────────────────────────────────────────────────────────

async def _post_init(application: Application) -> None:
    if AsyncIOScheduler is None:
        logger.warning("APScheduler is not installed — scheduled daily runs are disabled.")
        return

    settings = get_settings()
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

    # Pipeline commands
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("run", cmd_run))
    app.add_handler(CommandHandler("run_step_3", cmd_run_step_3))
    app.add_handler(CommandHandler("run_step_4", cmd_run_step_4))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("prices", cmd_prices))
    app.add_handler(CommandHandler("add_admin", cmd_add_admin))

    # Ready-image management commands
    app.add_handler(CommandHandler("images", cmd_images))
    app.add_handler(CommandHandler("delete_image", cmd_delete_image))
    app.add_handler(CommandHandler("flush_images", cmd_flush_images))
    app.add_handler(CommandHandler("process_backgrounds", cmd_process_backgrounds))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(btn_run_now, pattern="^run_now$"))
    app.add_handler(CallbackQueryHandler(btn_run_step_3, pattern="^run_step_3$"))
    app.add_handler(CallbackQueryHandler(btn_run_step_4, pattern="^run_step_4$"))
    app.add_handler(CallbackQueryHandler(btn_manage_images, pattern="^manage_images$"))
    app.add_handler(CallbackQueryHandler(btn_flush_images_ask, pattern="^flush_images_ask$"))
    app.add_handler(CallbackQueryHandler(btn_flush_images_confirm, pattern="^flush_images_confirm$"))
    app.add_handler(CallbackQueryHandler(btn_flush_images_cancel, pattern="^flush_images_cancel$"))
    app.add_handler(CallbackQueryHandler(btn_process_backgrounds, pattern="^process_backgrounds$"))

    # Photo upload — must be registered before the generic text fallback (if any)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_upload))

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
