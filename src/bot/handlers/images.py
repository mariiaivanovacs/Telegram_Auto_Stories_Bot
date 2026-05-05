"""
Background image management handlers.
- ready_images/: processed images used for story rendering (paginated gallery)
- Photo upload → auto-processed and added to ready_images/
- "Process backgrounds/" → batch-converts raw backgrounds/ folder
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from src.bot.auth import is_admin
from src.bot.keyboards import back_to_main
from src.config import get_settings
from src.sender import send_to_chat

logger = logging.getLogger(__name__)

PAGE_SIZE = 5

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import ContextTypes
except Exception:
    InlineKeyboardButton = InlineKeyboardMarkup = Update = ContextTypes = None


# ── Entry point ────────────────────────────────────────────────────────────────

async def btn_manage_images(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    await _show_page(query, page=0)


async def btn_images_page(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return
    page = int(query.data.split(":")[1])
    await _show_page(query, page=page)


async def btn_noop(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()


# ── Per-image actions ──────────────────────────────────────────────────────────

async def btn_img_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    from src.ready_images import list_images
    idx = int(query.data.split(":")[1])
    images = list_images()
    if not (1 <= idx <= len(images)):
        await query.answer("Фото не найдено.", show_alert=True)
        return

    img = images[idx - 1]
    try:
        with open(img["path"], "rb") as f:
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=f,
                caption=f"#{idx} {img['name']}",
            )
    except Exception as exc:
        logger.error("Preview send failed: %s", exc)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"❌ Не удалось отправить превью: {exc}",
        )


async def btn_img_delete_ask(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    from src.ready_images import list_images
    idx = int(query.data.split(":")[1])
    images = list_images()
    if not (1 <= idx <= len(images)):
        await query.answer("Фото не найдено.", show_alert=True)
        return

    img = images[idx - 1]
    current_page = _page_for_idx(idx, len(images))
    await query.edit_message_text(
        f"Удалить #{idx}?\n{img['name']}",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Да, удалить", callback_data=f"img_delete_confirm:{idx}"),
            InlineKeyboardButton("Отмена",       callback_data=f"img_page:{current_page}"),
        ]]),
    )


async def btn_img_delete_confirm(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    from src.ready_images import list_images
    idx = int(query.data.split(":")[1])
    images = list_images()
    if 1 <= idx <= len(images):
        img = images[idx - 1]
        Path(img["path"]).unlink(missing_ok=True)
        await query.answer(f"Удалено: {img['name']}")
        logger.info("Image deleted: %s by admin %d", img["name"], update.effective_user.id)
    else:
        await query.answer("Не найдено.")

    # Return to first page (indices shifted after delete)
    await _show_page(query, page=0)


# ── Bulk actions ───────────────────────────────────────────────────────────────

async def btn_flush_images_ask(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    from src.ready_images import list_images
    count = len(list_images())
    await query.edit_message_text(
        f"Удалить все {count} готовых фото?\nЭто нельзя отменить.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Да, удалить все", callback_data="flush_images_confirm"),
            InlineKeyboardButton("Отмена",           callback_data="manage_images"),
        ]]),
    )


async def btn_flush_images_confirm(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    from src.ready_images import flush_images
    count = flush_images()
    await query.edit_message_text(f"✅ Удалено {count} фото.", reply_markup=back_to_main())


async def btn_process_backgrounds(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(update.effective_user.id):
        return

    settings = get_settings()
    bg_dir = getattr(settings.story, "backgrounds_dir", "backgrounds")
    await query.edit_message_text(f"⏳ Обрабатываю фото из {bg_dir}/...")
    await asyncio.to_thread(_process_backgrounds_sync, update.effective_chat.id, bg_dir)


# ── Photo upload (MessageHandler) ─────────────────────────────────────────────

async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return

    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        await tg_file.download_to_drive(tmp_path)
        from src.ready_images import process_and_store
        saved = process_and_store(tmp_path)
        await update.message.reply_text(
            f"✅ Сохранено: {Path(saved).name}\n"
            "/start — вернуться в меню"
        )
    except Exception as exc:
        logger.error("Photo upload failed: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Не удалось обработать фото: {exc}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _show_page(query, page: int) -> None:
    from src.ready_images import list_images
    images = list_images()
    total = len(images)

    if not images:
        await query.edit_message_text(
            "Готовых фото нет.\n\n"
            "Отправьте фото в этот чат — оно будет обрезано и сохранено.\n"
            "Или нажмите «Обработать backgrounds/».",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Обработать backgrounds/", callback_data="process_backgrounds")],
                [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")],
            ]),
        )
        return

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    page_imgs = images[start:end]

    lines = [f"🖼 Готовые фото — страница {page + 1}/{total_pages} (всего: {total})\n"]
    for img in page_imgs:
        lines.append(f"#{img['id']}  {img['name']}")

    rows = []
    for img in page_imgs:
        rows.append([
            InlineKeyboardButton(f"👁 #{img['id']}", callback_data=f"img_preview:{img['id']}"),
            InlineKeyboardButton(f"🗑 #{img['id']}", callback_data=f"img_delete_ask:{img['id']}"),
        ])

    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Пред", callback_data=f"img_page:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if end < total:
        nav.append(InlineKeyboardButton("▶ След", callback_data=f"img_page:{page + 1}"))
    rows.append(nav)

    rows.append([InlineKeyboardButton("Обработать backgrounds/", callback_data="process_backgrounds")])
    rows.append([
        InlineKeyboardButton("🗑 Удалить все", callback_data="flush_images_ask"),
        InlineKeyboardButton("⬅️ Назад",       callback_data="back_to_main"),
    ])

    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows))


def _page_for_idx(idx: int, total: int) -> int:
    return max(0, (idx - 1) // PAGE_SIZE)


def _process_backgrounds_sync(chat_id: int, bg_dir: str) -> None:
    from src.ready_images import process_backgrounds_dir
    try:
        saved, failed = process_backgrounds_dir(bg_dir)
        lines = [f"✅ Обработано {len(saved)} фото → ready_images/."]
        if failed:
            lines.append(f"❌ Ошибки ({len(failed)}): {', '.join(failed[:5])}")
        send_to_chat(chat_id, "\n".join(lines))
    except FileNotFoundError:
        send_to_chat(chat_id, f"❌ Папка не найдена: {bg_dir}/")
    except Exception as exc:
        logger.error("process_backgrounds error: %s", exc, exc_info=True)
        send_to_chat(chat_id, f"❌ Ошибка: {exc}")
