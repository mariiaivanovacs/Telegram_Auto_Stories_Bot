"""Competition report export handler — sends an Excel (.xlsx) file."""
from __future__ import annotations

import io
import logging

import src.db as db
from src.bot.auth import is_admin
from src.bot.keyboards import back_to_main, report_keyboard

logger = logging.getLogger(__name__)

try:
    from telegram import Update
    from telegram.ext import ContextTypes
except Exception:
    Update = ContextTypes = None


async def btn_export_report(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    run = db.get_last_run()
    if not run:
        await query.edit_message_text(
            "❌ Нет завершённых запусков.\nЗапустите пайплайн сначала.",
            reply_markup=back_to_main(),
        )
        return

    ts = run["started_at"][:16].replace("T", " ")
    total = run["products_found"] + run["products_missing"]
    await query.edit_message_text(
        f"📊 Последний запуск: {ts}\n"
        f"Найдено: {run['products_found']} / {total}\n\n"
        "Скачайте отчёт в формате Excel:",
        reply_markup=report_keyboard(),
    )


async def btn_download_excel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    run = db.get_last_run()
    if not run:
        await query.edit_message_text(
            "❌ Нет данных для отчёта.",
            reply_markup=back_to_main(),
        )
        return

    await query.edit_message_text("⏳ Генерирую Excel-отчёт...")

    try:
        from src.report import build_competition_report_excel
        rows    = db.get_competition_report_data(run["id"])
        history = db.get_price_history_30d()
        xlsx_bytes = build_competition_report_excel(run, rows, history=history)

        ts_file = run["started_at"][:10]
        filename = f"report_{ts_file}.xlsx"

        history_runs = len({r["run_id"] for r in history}) if history else 0
        caption = (
            f"📊 Отчёт о конкурентах — {run['started_at'][:16].replace('T', ' ')}\n"
            f"История: {history_runs} запуск(ов) за 30 дней · "
            "3 листа: Сводка / Текущий запуск / История 30 дней"
        )

        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=io.BytesIO(xlsx_bytes),
            filename=filename,
            caption=caption,
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Используйте /start для возврата в меню.",
        )
    except Exception as exc:
        logger.error("Excel report generation failed: %s", exc, exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Ошибка генерации отчёта: {exc}",
        )
