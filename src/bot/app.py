"""
Bot application setup.
Registers all handlers and command list, starts polling.
"""
from __future__ import annotations

import logging

from src.bot import auth, scheduler
from src.bot.handlers import admin, channels, images, pipeline, prices, report
from src.bot.handlers import settings as settings_hdl
from src.config import get_settings
from src.main import setup_logging

logger = logging.getLogger(__name__)

try:
    from telegram import BotCommand, Update
    from telegram.error import Conflict
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )
except Exception:
    Application = BotCommand = Update = Conflict = None
    CallbackQueryHandler = CommandHandler = MessageHandler = filters = None


_COMMANDS = [
    ("start",  "Открыть главное меню"),
    ("run",    "Запустить сбор цен и генерацию сторис прямо сейчас"),
    ("status", "Показать статус и результаты последнего запуска"),
    ("ping",   "Проверить, что бот работает"),
    ("admin",  "Войти как администратор (потребуется пароль)"),
]


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(
        [BotCommand(cmd, desc) for cmd, desc in _COMMANDS]
    )
    settings = get_settings()
    await scheduler.setup(app, settings.schedule.run_time, settings.schedule.timezone)


async def _post_shutdown(app: Application) -> None:
    await scheduler.teardown(app)


async def _on_error(update: object, context) -> None:
    logger.error("Unhandled bot update error: update=%s error=%s", update, context.error, exc_info=context.error)


def run_bot() -> None:
    setup_logging()
    settings = get_settings()

    if not settings.bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set — bot will not start")
        return

    app = (
        Application.builder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    # ── ConversationHandlers first (highest priority) ──────────────────────────
    app.add_handler(auth.make_admin_conv())
    app.add_handler(channels.make_add_channel_conv())
    app.add_handler(prices.make_price_edit_conv())
    app.add_handler(pipeline.make_manual_price_conv())

    # ── Commands ───────────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",  admin.cmd_start))
    app.add_handler(CommandHandler("ping",   admin.cmd_ping))
    app.add_handler(CommandHandler("status", admin.cmd_status))
    app.add_handler(CommandHandler("run",    pipeline.cmd_run))

    # ── Inline button callbacks ────────────────────────────────────────────────

    # Navigation
    app.add_handler(CallbackQueryHandler(admin.btn_back_to_main, pattern="^back_to_main$"))
    app.add_handler(CallbackQueryHandler(admin.btn_show_status,  pattern="^show_status$"))
    app.add_handler(CallbackQueryHandler(admin.btn_debug_menu,   pattern="^debug_menu$"))

    # Pipeline
    app.add_handler(CallbackQueryHandler(pipeline.btn_run_now,       pattern="^run_now$"))
    app.add_handler(CallbackQueryHandler(pipeline.btn_run_step_3,    pattern="^run_step_3$"))
    app.add_handler(CallbackQueryHandler(pipeline.btn_run_step_4,    pattern="^run_step_4$"))
    app.add_handler(CallbackQueryHandler(pipeline.btn_select_design, pattern=r"^select_design:\d+$"))
    # Large price change confirmations
    app.add_handler(CallbackQueryHandler(pipeline.btn_approve_price,  pattern=r"^(approve_price_\d+|approve_price:\d+)$"))
    app.add_handler(CallbackQueryHandler(pipeline.btn_preserve_price, pattern=r"^(preserve_price_\d+|old_price:\d+)$"))

    # Images — gallery
    app.add_handler(CallbackQueryHandler(images.btn_manage_images,        pattern="^manage_images$"))
    app.add_handler(CallbackQueryHandler(images.btn_images_page,          pattern=r"^img_page:\d+$"))
    app.add_handler(CallbackQueryHandler(images.btn_noop,                 pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(images.btn_img_preview,          pattern=r"^img_preview:\d+$"))
    app.add_handler(CallbackQueryHandler(images.btn_img_delete_ask,       pattern=r"^img_delete_ask:\d+$"))
    app.add_handler(CallbackQueryHandler(images.btn_img_delete_confirm,   pattern=r"^img_delete_confirm:\d+$"))
    # Images — bulk
    app.add_handler(CallbackQueryHandler(images.btn_flush_images_ask,     pattern="^flush_images_ask$"))
    app.add_handler(CallbackQueryHandler(images.btn_flush_images_confirm, pattern="^flush_images_confirm$"))
    app.add_handler(CallbackQueryHandler(images.btn_process_backgrounds,  pattern="^process_backgrounds$"))

    # Settings
    app.add_handler(CallbackQueryHandler(settings_hdl.btn_manage_settings,   pattern="^manage_settings$"))
    app.add_handler(CallbackQueryHandler(settings_hdl.btn_set_schedule_time, pattern="^set_schedule_time$"))
    app.add_handler(CallbackQueryHandler(settings_hdl.btn_set_max_posts,     pattern="^set_max_posts$"))
    app.add_handler(CallbackQueryHandler(settings_hdl.btn_max_posts_select,  pattern=r"^max_posts:\d+$"))

    # Channels
    app.add_handler(CallbackQueryHandler(channels.btn_manage_channels, pattern="^manage_channels$"))
    app.add_handler(CallbackQueryHandler(channels.btn_toggle_channel,  pattern=r"^toggle_ch:\d+$"))

    # Prices
    app.add_handler(CallbackQueryHandler(prices.btn_manage_prices, pattern="^manage_prices$"))

    # Report
    app.add_handler(CallbackQueryHandler(report.btn_export_report,   pattern="^export_report$"))
    app.add_handler(CallbackQueryHandler(report.btn_download_excel,  pattern="^report_download_excel$"))

    # ── Message handlers (lowest priority) ────────────────────────────────────
    # Groups are independent: each handler runs only if its own precondition holds.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, settings_hdl.handle_schedule_time_input), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, pipeline.handle_waiting_price_text), group=2)
    app.add_handler(MessageHandler(filters.PHOTO, images.handle_photo_upload))
    app.add_error_handler(_on_error)

    logger.info("Admin bot polling started")
    try:
        app.run_polling(drop_pending_updates=True)
    except Conflict:
        logger.error(
            "CONFLICT — another bot instance is already running.\n"
            "Stop the other instance first: docker compose down"
        )
