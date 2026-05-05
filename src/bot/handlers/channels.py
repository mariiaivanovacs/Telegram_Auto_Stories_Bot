"""
Channel management handlers.
Channels added or toggled here are persisted in DB and survive server restarts.
Channels from config.yaml are seeded on startup but their is_active state
is never overwritten if already set in DB.
"""
from __future__ import annotations

import logging

import src.db as db
from src.bot.auth import is_admin
from src.bot.keyboards import back_to_main, channels_keyboard

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

ASK_USERNAME = 1
ASK_DISPLAY = 2


# ── List / toggle ──────────────────────────────────────────────────────────────

async def btn_manage_channels(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    channels = db.get_all_channels()
    await query.edit_message_text(
        f"📡 Каналы конкурентов ({len(channels)}):",
        reply_markup=channels_keyboard(channels),
    )


async def btn_toggle_channel(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    channel_id = int(query.data.split(":")[1])
    channel = db.toggle_channel(channel_id)
    if not channel:
        await query.answer("Канал не найден.", show_alert=True)
        return
    status = "активирован ✅" if channel["is_active"] else "отключён ⏸"
    await query.answer(f"@{channel['username']} {status}")
    channels = db.get_all_channels()
    await query.edit_message_text(
        f"📡 Каналы конкурентов ({len(channels)}):",
        reply_markup=channels_keyboard(channels),
    )


# ── Add channel (conversation) ─────────────────────────────────────────────────

async def _btn_add_channel(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await query.edit_message_text(
        "Введите @username нового канала\n"
        "(например: @iphone_price_msk)\n\n"
        "/cancel — отмена"
    )
    return ASK_USERNAME


async def _handle_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()
    username = raw.lstrip("@").strip()
    if not username or " " in username:
        await update.message.reply_text(
            "❌ Неверный формат. Введите @username без пробелов:"
        )
        return ASK_USERNAME
    context.user_data["new_channel_username"] = username
    await update.message.reply_text(
        f"Канал: @{username}\n\n"
        "Введите название для отображения\n"
        "(например: iPhone MSK, или отправьте — чтобы пропустить):"
    )
    return ASK_DISPLAY


async def _handle_display(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    display = "" if text == "—" else text
    username = context.user_data.pop("new_channel_username", "")
    if not username:
        await update.message.reply_text("❌ Ошибка: username потерян. Начните заново.")
        return ConversationHandler.END
    try:
        channel = db.upsert_channel(username, display)
        name = channel.get("display_name") or f"@{channel['username']}"
        await update.message.reply_text(
            f"✅ Канал добавлен: {name} (@{channel['username']})\n"
            "Используйте /start для возврата в меню."
        )
        logger.info("Channel added: @%s by admin %d", username, update.effective_user.id)
    except Exception as exc:
        logger.error("Add channel failed: %s", exc)
        await update.message.reply_text(f"❌ Ошибка при добавлении: {exc}")
    return ConversationHandler.END


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_channel_username", None)
    await update.message.reply_text("Отменено. Используйте /start.")
    return ConversationHandler.END


def make_add_channel_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(_btn_add_channel, pattern="^add_channel$")],
        states={
            ASK_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_username)],
            ASK_DISPLAY:  [MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_display)],
        },
        fallbacks=[CommandHandler("cancel", _cancel)],
    )
