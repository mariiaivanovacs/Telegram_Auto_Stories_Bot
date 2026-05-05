"""Settings panel: daily schedule time and max posts per channel."""
from __future__ import annotations

import logging
import re

import src.db as db
from src.bot.auth import is_admin
from src.bot.keyboards import max_posts_keyboard, settings_keyboard
from src.config import get_settings

logger = logging.getLogger(__name__)

try:
    from telegram import Update
    from telegram.ext import ContextTypes
except Exception:
    Update = ContextTypes = None

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_WAITING_TIME = "waiting_schedule_time"


def _current_settings() -> tuple[str, int]:
    run_time = db.get_schedule_time(get_settings().schedule.run_time)
    max_posts = db.get_max_posts()
    return run_time, max_posts


async def btn_manage_settings(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    run_time, max_posts = _current_settings()
    await query.edit_message_text(
        "⚙️ Настройки автопайплайна",
        reply_markup=settings_keyboard(run_time, max_posts),
    )


async def btn_set_schedule_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    ctx.user_data[_WAITING_TIME] = True
    await query.edit_message_text(
        "Введите время запуска в формате ЧЧ:ММ (например, 10:30):"
    )


async def handle_schedule_time_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if not is_admin(update.effective_user.id):
        return
    if not ctx.user_data.get(_WAITING_TIME):
        return

    text = update.message.text.strip()
    if not _TIME_RE.match(text):
        await update.message.reply_text(
            "Неверный формат. Введите время как ЧЧ:ММ (например, 09:00):"
        )
        return

    ctx.user_data.pop(_WAITING_TIME, None)
    db.set_schedule_time(text)
    await _apply_reschedule(ctx, text)
    run_time, max_posts = _current_settings()
    await update.message.reply_text(
        f"✅ Время обновлено: {text}\n\n⚙️ Настройки автопайплайна",
        reply_markup=settings_keyboard(run_time, max_posts),
    )


async def btn_set_max_posts(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    current = db.get_max_posts()
    await query.edit_message_text(
        f"Выберите сколько постов анализировать на канал (текущее: {current}):",
        reply_markup=max_posts_keyboard(current),
    )


async def btn_max_posts_select(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    value = int(query.data.split(":")[1])
    db.set_max_posts(value)
    run_time, max_posts = _current_settings()
    await query.edit_message_text(
        "⚙️ Настройки автопайплайна",
        reply_markup=settings_keyboard(run_time, max_posts),
    )


async def _apply_reschedule(ctx, run_time: str) -> None:
    from src.bot import scheduler as sched
    try:
        settings = get_settings()
        await sched.reschedule(ctx.application, run_time, settings.schedule.timezone)
    except Exception as exc:
        logger.error("Reschedule failed: %s", exc)
