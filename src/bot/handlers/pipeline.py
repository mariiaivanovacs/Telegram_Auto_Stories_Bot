"""Pipeline run handlers: full pipeline, step 3 (stories), step 4 (font test)."""
from __future__ import annotations

import asyncio
import logging

import src.db as db
import src.lock as lock
from src.bot.auth import is_admin
from src.config import get_settings
from src.sender import send_photo_to_chat, send_to_chat, send_to_chat_markup

logger = logging.getLogger(__name__)

try:
    from telegram import Update
    from telegram.ext import (
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        ConversationHandler,
        MessageHandler,
        filters,
    )
except Exception:
    Update = ContextTypes = ConversationHandler = CallbackQueryHandler = None
    CommandHandler = MessageHandler = filters = None


# ── Command handlers ───────────────────────────────────────────────────────────

# ── Large price change confirmation ───────────────────────────────────────────
# Sent by main.py when delta > large_change_threshold.
# Buttons: approve / preserve / manual.

async def btn_approve_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await _safe_answer(query)
    if not is_admin(update.effective_user.id):
        logger.warning("Ignoring approve click from non-admin user_id=%s", update.effective_user.id)
        return ConversationHandler.END
    change_id = _change_id_from_callback(query.data)
    logger.info("Price approval clicked: change_id=%d admin=%d", change_id, update.effective_user.id)
    change = db.get_pending_price_change(change_id)
    if not change:
        await query.edit_message_text("❌ Изменение цены не найдено.")
        return ConversationHandler.END
    db.resolve_pending_price_change(change_id, "approved", update.effective_user.id)
    db.update_product_price(change["product_id"], change["proposed_price"])
    price_str = f"{change['proposed_price']:,}".replace(",", " ") + " ₽"
    await _safe_edit_or_reply(
        query,
        f"✅ Цена подтверждена!\n{change['canonical_name']}: {price_str}"
    )
    return ConversationHandler.END


async def btn_preserve_price(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _safe_answer(query)
    if not is_admin(update.effective_user.id):
        logger.warning("Ignoring preserve click from non-admin user_id=%s", update.effective_user.id)
        return
    change_id = _change_id_from_callback(query.data)
    logger.info("Price preserve clicked: change_id=%d admin=%d", change_id, update.effective_user.id)
    change = db.get_pending_price_change(change_id)
    if not change:
        await query.edit_message_text("❌ Изменение цены не найдено.")
        return
    db.resolve_pending_price_change(change_id, "preserved", update.effective_user.id)
    old = change.get("old_price")
    price_str = f"{old:,}".replace(",", " ") + " ₽" if old is not None else "—"
    await _safe_edit_or_reply(
        query,
        f"✅ Старая цена сохранена.\n{change['canonical_name']}: {price_str}"
    )


ENTER_MANUAL_PRICE = 10


async def btn_manual_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await _safe_answer(query)
    if not is_admin(update.effective_user.id):
        logger.warning("Ignoring manual click from non-admin user_id=%s", update.effective_user.id)
        return ConversationHandler.END
    change_id = _change_id_from_callback(query.data)
    logger.info("Manual price clicked: change_id=%d admin=%d", change_id, update.effective_user.id)
    change = db.get_pending_price_change(change_id)
    if not change:
        await query.edit_message_text("❌ Изменение цены не найдено.")
        return ConversationHandler.END
    db.mark_pending_price_change_for_manual(change_id, update.effective_user.id)
    context.user_data["manual_change_id"] = change_id
    await _safe_edit_or_reply(
        query,
        f"Товар: {change['canonical_name']}\n"
        "Введите свою цену (только цифры, например: 94500):\n"
        "Или /cancel для отмены"
    )
    return ENTER_MANUAL_PRICE


async def _handle_manual_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    change_id = context.user_data.pop("manual_change_id", None)
    if change_id is None:
        return ConversationHandler.END
    text = update.message.text.strip()
    digits = "".join(c for c in text if c.isdigit())
    if not digits or not 1_000 <= int(digits) <= 10_000_000:
        context.user_data["manual_change_id"] = change_id
        await update.message.reply_text(
            "❌ Неверная цена. Введите число от 1 000 до 10 000 000.\n"
            "Или /cancel для отмены"
        )
        return ENTER_MANUAL_PRICE
    price = int(digits)
    change = db.get_pending_price_change(change_id)
    if not change:
        await update.message.reply_text("❌ Изменение не найдено.")
        return ConversationHandler.END
    db.resolve_pending_price_change(change_id, "manual", update.effective_user.id, price)
    db.update_product_price(change["product_id"], price)
    price_str = f"{price:,}".replace(",", " ") + " ₽"
    await update.message.reply_text(
        f"✅ Установлена своя цена!\n{change['canonical_name']}: {price_str}"
    )
    return ConversationHandler.END


async def _cancel_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("manual_change_id", None)
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


def make_manual_price_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(btn_manual_price, pattern=r"^(manual_price_\d+|manual_price:\d+)$")],
        states={ENTER_MANUAL_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_manual_price)]},
        fallbacks=[CommandHandler("cancel", _cancel_manual)],
    )


async def handle_waiting_price_text(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if not is_admin(update.effective_user.id):
        return

    wait = db.get_latest_waiting_pipeline()
    if not wait:
        return

    changes = db.get_unresolved_price_changes_for_run(wait["run_id"])
    if len(changes) != 1:
        await update.message.reply_text("Есть несколько цен на подтверждение. Нажмите /run, я пришлю кнопки заново.")
        return

    change = changes[0]
    text = update.message.text.strip().lower()
    digits = "".join(ch for ch in text if ch.isdigit())

    if text in {"да", "yes", "y", "ок", "ok", "+"}:
        db.resolve_pending_price_change(change["id"], "approved", update.effective_user.id)
        db.update_product_price(change["product_id"], change["proposed_price"])
        await update.message.reply_text(
            f"✅ Цена подтверждена.\n{change['canonical_name']}: {_format_money(change['proposed_price'])}"
        )
        return

    if any(word in text for word in ("стара", "old", "остав", "keep")):
        db.resolve_pending_price_change(change["id"], "preserved", update.effective_user.id)
        await update.message.reply_text(
            f"✅ Старая цена сохранена.\n{change['canonical_name']}: {_format_money(change.get('old_price'))}"
        )
        return

    if digits:
        price = int(digits)
        if 1_000 <= price <= 10_000_000:
            db.resolve_pending_price_change(change["id"], "manual", update.effective_user.id, price)
            db.update_product_price(change["product_id"], price)
            await update.message.reply_text(
                f"✅ Установлена своя цена.\n{change['canonical_name']}: {_format_money(price)}"
            )
            return

    await update.message.reply_text(
        "Пайплайн ждёт цену. Напишите: да, старая, или свою цену цифрами."
    )


def _change_id_from_callback(data: str) -> int:
    return int(data.rsplit(":", 1)[-1] if ":" in data else data.rsplit("_", 1)[-1])


async def _safe_answer(query) -> None:
    try:
        await query.answer()
    except Exception as exc:
        logger.warning("Callback acknowledgement failed; processing button anyway: %s", exc)


async def _safe_edit_or_reply(query, text: str) -> None:
    try:
        await query.edit_message_text(text)
    except Exception as exc:
        logger.warning("Callback message edit failed; sending reply instead: %s", exc)
        if query.message:
            await query.message.reply_text(text)


# ── Command handlers ───────────────────────────────────────────────────────────

async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    await _trigger(update, context)


# ── Button callbacks ───────────────────────────────────────────────────────────

async def btn_run_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await _trigger(update, context, from_button=True)


async def btn_run_step_3(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    if lock.is_locked():
        await query.edit_message_text("⚠️ Запуск уже выполняется.")
        return
    await query.edit_message_text("⏳ Шаг 3: парсинг → цены → сторис...")
    await asyncio.to_thread(_run_step_3_sync, update.effective_chat.id)


async def btn_run_step_4(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    if lock.is_locked():
        await query.edit_message_text("⚠️ Запуск уже выполняется.")
        return
    await query.edit_message_text("⏳ Шаг 4: рендер тестовых сторис...")
    await asyncio.to_thread(_run_step_4_sync, update.effective_chat.id)


# ── Trigger logic ──────────────────────────────────────────────────────────────

async def _trigger(
    update: Update,
    _ctx: ContextTypes.DEFAULT_TYPE,
    from_button: bool = False,
) -> None:
    if lock.is_locked():
        if _resend_waiting_approval(update.effective_chat.id):
            msg = "⏸ Пайплайн уже ждёт подтверждение цены. Я отправил свежие кнопки выше."
        else:
            msg = "⚠️ Запуск уже выполняется."
        if from_button:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return

    chat_id = update.effective_chat.id
    notice = "⏳ Запускаю пайплайн..."
    if from_button:
        await update.callback_query.edit_message_text(notice)
    else:
        await update.message.reply_text(notice)

    def progress(msg: str) -> None:
        send_to_chat(chat_id, msg)

    await asyncio.to_thread(_run_pipeline_sync, progress, chat_id)


def _run_pipeline_sync(progress_cb=None, chat_id: int | None = None) -> None:
    try:
        from src.main import run_pipeline
        run_pipeline(progress_cb=progress_cb, wait_chat_id=chat_id)
    except Exception as exc:
        logger.error("Pipeline error: %s", exc, exc_info=True)


def _resend_waiting_approval(chat_id: int) -> bool:
    wait = db.get_latest_waiting_pipeline()
    if not wait:
        return False

    changes = db.get_unresolved_price_changes_for_run(wait["run_id"])
    if not changes:
        return False

    for change in changes:
        send_to_chat_markup(
            chat_id,
            _format_pending_change_prompt(change),
            {
                "inline_keyboard": [
                    [
                        {"text": "ДА", "callback_data": f"approve_price:{change['id']}"},
                        {"text": "оставить старую цену", "callback_data": f"old_price:{change['id']}"},
                    ],
                    [
                        {"text": "написать свою цену", "callback_data": f"manual_price:{change['id']}"},
                    ],
                ]
            },
        )
    return True


# ── Step 3: fetch → price → stories ───────────────────────────────────────────

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
            send_to_chat(chat_id, "⚠️ Нет активных каналов конкурентов.")
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
            send_to_chat(chat_id, f"🔐 {exc}\nИспользуйте скрипт create_session.py для авторизации.")
        except Exception as exc:
            logger.error("Step 3 error: %s", exc, exc_info=True)
            db.finish_run(run_id, "failed", 0, 0, [str(exc)])
            send_to_chat(chat_id, f"❌ Шаг 3: ошибка — {exc}")
    finally:
        lock.release()


# ── Step 4: font / text preview ────────────────────────────────────────────────

def _run_step_4_sync(chat_id: int) -> None:
    if not lock.acquire():
        send_to_chat(chat_id, "⚠️ Запуск уже выполняется.")
        return

    try:
        from src.ready_images import pick_for_render

        settings = get_settings()
        db.init(settings)
        price_results = _price_results_from_db()

        ready_paths = pick_for_render()
        font_variants = _step_4_font_variants(settings.story)

        if ready_paths:
            send_to_chat(chat_id, "🎨 Рендерю тестовые сторис из готовых фото...")
            from src.story import generate_price_text_stories_from_ready
            story_paths = generate_price_text_stories_from_ready(
                price_results, settings.story, ready_paths,
                output_dir="output/step_4_text_tests",
                font_paths=font_variants,
            )
        else:
            send_to_chat(chat_id, "🎨 Готовых фото нет — рендерю из оригинальных фонов...")
            from src.story import generate_price_text_stories
            story_paths = generate_price_text_stories(
                price_results, settings.story,
                output_dir="output/step_4_text_tests",
                font_paths=font_variants,
            )

        sent = sum(1 for p in story_paths if send_photo_to_chat(chat_id, p))
        send_to_chat(
            chat_id,
            f"Шаг 4 завершён: {sent}/{len(story_paths)} тестовых сторис.\n"
            "Вариант 1 — текущий шрифт, 2 — SF UI, 3 — Avenir.",
        )
    except Exception as exc:
        logger.error("Step 4 error: %s", exc, exc_info=True)
        send_to_chat(chat_id, f"❌ Шаг 4: ошибка — {exc}")
    finally:
        lock.release()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _price_results_from_db() -> list[dict]:
    results = []
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


def _format_pending_change_prompt(change: dict) -> str:
    return "\n".join([
        "⏸ Пайплайн ждёт подтверждение цены",
        change["canonical_name"],
        f"Старая: {_format_money(change.get('old_price'))}",
        f"Новая: {_format_money(change.get('proposed_price'))}",
        "",
        "Выберите действие, после ответа пайплайн продолжит сторис и отправку.",
    ])


def _step_4_font_variants(story_cfg) -> list[str | None]:
    return [
        getattr(story_cfg, "font_path", None),
        _first_existing([
            "/Users/mariaivanova/Library/Fonts/SF-UI-DISPLAY-SEMIBOLD.TTF",
            "/System/Library/Fonts/SFNS.ttf",
        ]),
        _first_existing([
            "/System/Library/Fonts/Avenir Next.ttc",
            "/System/Library/Fonts/Avenir.ttc",
        ]),
    ]


def _first_existing(paths: list[str]) -> str | None:
    from pathlib import Path
    for p in paths:
        if Path(p).exists():
            return p
    return None


# ── Formatting helpers (also used in tests) ────────────────────────────────────

def _parse_price_input(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _format_money(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", " ") + " ₽"


def _format_delta(value: int | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,}".replace(",", " ") + " ₽"


def _format_matched_line_calculations(match_results: dict, discount: int) -> list[str]:
    grouped: dict[str, list[str]] = {}
    for match in match_results.values():
        for item in (match.get("matched_lines") or []):
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
        f"Канал конкурента: @{result.get('source_channel') or match.get('source_channel') or '—'}",
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
