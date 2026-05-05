"""
Manage prices handler.
Shows all products with current prices; admin can tap any product to set a new price.
These prices are what the pipeline uses as the current/display price.
"""
from __future__ import annotations

import logging

import src.db as db
from src.bot.auth import is_admin
from src.bot.keyboards import back_to_main, prices_keyboard

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

ENTER_PRICE = 1


# ── List ───────────────────────────────────────────────────────────────────────

async def btn_manage_prices(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    products = db.get_all_products()
    await query.edit_message_text(
        "💰 Управление ценами\n\nВыберите товар для изменения цены:",
        reply_markup=prices_keyboard(products),
    )


# ── Edit price (conversation) ──────────────────────────────────────────────────

async def _btn_price_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    product_id = int(query.data.split(":")[1])
    product = db.get_product_by_id(product_id)
    if not product:
        await query.edit_message_text("❌ Товар не найден.")
        return ConversationHandler.END

    context.user_data["editing_product"] = product
    price = product.get("current_price")
    price_str = f"{price:,}".replace(",", " ") + " ₽" if price is not None else "—"
    default = product.get("default_price")
    default_str = f"{default:,}".replace(",", " ") + " ₽" if default is not None else "—"

    await query.edit_message_text(
        f"Товар: {product['display_name']}\n"
        f"Текущая цена: {price_str}\n"
        f"Цена по умолчанию: {default_str}\n\n"
        "Введите новую цену (только цифры, например: 94500):\n"
        "Или /cancel для отмены"
    )
    return ENTER_PRICE


async def _handle_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    product = context.user_data.get("editing_product")
    if not product:
        return ConversationHandler.END

    text = update.message.text.strip()
    digits = "".join(c for c in text if c.isdigit())

    if not digits:
        await update.message.reply_text(
            "❌ Неверный формат. Введите число, например: 94500\n"
            "Или /cancel для отмены"
        )
        return ENTER_PRICE

    price = int(digits)
    if not 1_000 <= price <= 10_000_000:
        await update.message.reply_text(
            "❌ Цена вне допустимого диапазона (1 000 — 10 000 000 ₽).\n"
            "Или /cancel для отмены"
        )
        return ENTER_PRICE

    db.update_product_price(product["id"], price)
    context.user_data.pop("editing_product", None)

    price_str = f"{price:,}".replace(",", " ") + " ₽"
    logger.info(
        "Price updated: %s → %d by admin %d",
        product["display_name"], price, update.effective_user.id,
    )
    await update.message.reply_text(
        f"✅ Цена обновлена!\n"
        f"{product['display_name']}: {price_str}\n\n"
        "Используйте /start для возврата в меню."
    )
    return ConversationHandler.END


async def _cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("editing_product", None)
    await update.message.reply_text("Отменено. Используйте /start.")
    return ConversationHandler.END


def make_price_edit_conv() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(_btn_price_select, pattern=r"^price_select:\d+$")
        ],
        states={
            ENTER_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_price_input)
            ]
        },
        fallbacks=[CommandHandler("cancel", _cancel)],
    )
