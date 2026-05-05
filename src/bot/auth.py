"""
Admin auth: password-based access via /admin command.
After a user is granted access they are stored permanently in the admins DB table.
TELEGRAM_ADMIN_ID in .env is always the bootstrap super-admin.
"""
from __future__ import annotations

import logging

import src.db as db
from src.config import get_settings

logger = logging.getLogger(__name__)

try:
    from telegram import Update
    from telegram.ext import (
        CommandHandler,
        ContextTypes,
        ConversationHandler,
        MessageHandler,
        filters,
    )
except Exception:
    Update = ContextTypes = ConversationHandler = CommandHandler = MessageHandler = filters = None

WAITING_PASSWORD = 1


def is_admin(user_id: int) -> bool:
    try:
        return db.is_admin(user_id)
    except Exception as exc:
        logger.error("Admin check failed for %d: %s", user_id, exc)
        return False


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if is_admin(update.effective_user.id):
        await update.message.reply_text(
            "Вы уже администратор.\nИспользуйте /start для управления."
        )
        return ConversationHandler.END
    await update.message.reply_text("Введите пароль администратора:")
    return WAITING_PASSWORD


async def _handle_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    settings = get_settings()
    password = update.message.text.strip()

    if not settings.admin_password:
        await update.message.reply_text(
            "❌ Пароль администратора не настроен на сервере.\n"
            "Добавьте ADMIN_PASSWORD в .env и перезапустите бота."
        )
        return ConversationHandler.END

    if password == settings.admin_password:
        user = update.effective_user
        added = db.add_admin(user.id, user.username or "", added_by=0)
        if added:
            logger.info("New admin via password: %d (@%s)", user.id, user.username or "")
            await update.message.reply_text("✅ Доступ предоставлен!\nИспользуйте /start.")
        else:
            await update.message.reply_text("ℹ️ Вы уже в списке. Используйте /start.")
    else:
        await update.message.reply_text("❌ Неверный пароль.")

    return ConversationHandler.END


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Отменено.")
    return ConversationHandler.END


def make_admin_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("admin", cmd_admin)],
        states={
            WAITING_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_password)
            ]
        },
        fallbacks=[CommandHandler("cancel", _cancel)],
    )
