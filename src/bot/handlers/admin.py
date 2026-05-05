"""Core admin commands: /start, /ping, /status, and main-menu callbacks."""
from __future__ import annotations

import logging

import src.db as db
from src.bot.auth import is_admin
from src.bot.keyboards import debug_menu, main_menu

logger = logging.getLogger(__name__)

try:
    from telegram import Update
    from telegram.ext import ContextTypes
except Exception:
    Update = ContextTypes = None


async def cmd_ping(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong")


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "Нет доступа.\nВведите /admin для получения прав администратора."
        )
        return
    await update.message.reply_text(
        _status_header(),
        reply_markup=main_menu(),
    )


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return
    await update.message.reply_text(_status_text())


# ── Callback buttons ───────────────────────────────────────────────────────────

async def btn_back_to_main(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await query.edit_message_text(_status_header(), reply_markup=main_menu())


async def btn_show_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await query.edit_message_text(_status_text(), reply_markup=main_menu())


async def btn_debug_menu(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await query.edit_message_text("🔧 Отладка:", reply_markup=debug_menu())


# ── Helpers ────────────────────────────────────────────────────────────────────

def _status_header() -> str:
    run = db.get_last_run()
    if run:
        ts = run["started_at"][:16].replace("T", " ")
        icon = "✅" if run["status"] == "success" else "⚠️"
        line = f"Последний запуск: {ts} {icon}"
    else:
        line = "Запусков ещё не было"
    return f"🤖 Панель управления\n{line}"


def _status_text() -> str:
    run = db.get_last_run()
    if not run:
        return "Запусков ещё не было."
    ts = run["started_at"][:16].replace("T", " ")
    icon = "✅" if run["status"] == "success" else ("⚠️" if run["status"] == "partial" else "❌")
    total = run["products_found"] + run["products_missing"]
    return (
        f"{icon} Последний запуск: {ts}\n"
        f"Статус: {run['status']}\n"
        f"Найдено: {run['products_found']} / {total}\n"
        f"Пропущено: {run['products_missing']}"
    )
