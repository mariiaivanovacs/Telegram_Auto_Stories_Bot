"""All InlineKeyboardMarkup layouts in one place."""
from __future__ import annotations

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
except Exception:
    InlineKeyboardButton = InlineKeyboardMarkup = None


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Запустить пайплайн", callback_data="run_now")],
        [
            InlineKeyboardButton("🖼 Управление фото",    callback_data="manage_images"),
            InlineKeyboardButton("📡 Каналы",             callback_data="manage_channels"),
        ],
        [
            InlineKeyboardButton("📊 Экспорт отчёта",    callback_data="export_report"),
            InlineKeyboardButton("💰 Управление ценами",  callback_data="manage_prices"),
        ],
        [
            InlineKeyboardButton("⚙️ Настройки",          callback_data="manage_settings"),
            InlineKeyboardButton("📋 Статус",             callback_data="show_status"),
        ],
        [InlineKeyboardButton("🔧 Отладка",               callback_data="debug_menu")],
    ])


def debug_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Шаг 3: Сторис",      callback_data="run_step_3")],
        [InlineKeyboardButton("Шаг 4: Тест шрифта", callback_data="run_step_4")],
        [InlineKeyboardButton("⬅️ Назад",            callback_data="back_to_main")],
    ])


def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="back_to_main")]
    ])


def channels_keyboard(channels: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        status = "✅" if ch["is_active"] else "⏸"
        label = f"{status} @{ch['username']}"
        if ch.get("display_name"):
            label += f" ({ch['display_name']})"
        action = "Отключить" if ch["is_active"] else "Включить"
        rows.append([
            InlineKeyboardButton(label, callback_data=f"ch_info:{ch['id']}"),
            InlineKeyboardButton(action, callback_data=f"toggle_ch:{ch['id']}"),
        ])
    rows.append([
        InlineKeyboardButton("➕ Добавить канал", callback_data="add_channel"),
        InlineKeyboardButton("⬅️ Назад",          callback_data="back_to_main"),
    ])
    return InlineKeyboardMarkup(rows)


def prices_keyboard(products: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for p in products:
        price = p.get("current_price")
        price_str = f"{price:,}".replace(",", " ") + " ₽" if price is not None else "—"
        rows.append([InlineKeyboardButton(
            f"{p['display_name']} — {price_str}",
            callback_data=f"price_select:{p['id']}",
        )])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(rows)


def images_keyboard(has_images: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("Обработать backgrounds/", callback_data="process_backgrounds")]]
    if has_images:
        rows.append([InlineKeyboardButton("🗑 Удалить все готовые фото", callback_data="flush_images_ask")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(rows)


def report_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 Скачать отчёт (Excel)",   callback_data="report_download_excel")],
        [InlineKeyboardButton("⬅️ Назад",                    callback_data="back_to_main")],
    ])


_DAYS_RU = {
    "mon": "Понедельник", "tue": "Вторник", "wed": "Среда",
    "thu": "Четверг",     "fri": "Пятница", "sat": "Суббота", "sun": "Воскресенье",
}
_DAYS_SHORT = {
    "mon": "Пн", "tue": "Вт", "wed": "Ср",
    "thu": "Чт", "fri": "Пт", "sat": "Сб", "sun": "Вс",
}


def settings_keyboard(weekday: str, run_time: str, max_posts: int) -> InlineKeyboardMarkup:
    day_label = _DAYS_SHORT.get(weekday, weekday)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📅 Расписание: {day_label} в {run_time}", callback_data="noop"
        )],
        [
            InlineKeyboardButton("Изменить день",   callback_data="set_schedule_day"),
            InlineKeyboardButton("Изменить время",  callback_data="set_schedule_time"),
        ],
        [InlineKeyboardButton(
            f"📨 Постов на канал: {max_posts}", callback_data="noop"
        )],
        [InlineKeyboardButton("Изменить кол-во постов", callback_data="set_max_posts")],
        [InlineKeyboardButton("⬅️ Назад",                callback_data="back_to_main")],
    ])


def weekday_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"weekday:{code}")]
        for code, label in _DAYS_RU.items()
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="manage_settings")])
    return InlineKeyboardMarkup(rows)


def max_posts_keyboard(current: int) -> InlineKeyboardMarkup:
    options = [5, 10, 15, 20, 25, 30]
    row1 = [
        InlineKeyboardButton(
            f"{'✅ ' if v == current else ''}{v}", callback_data=f"max_posts:{v}"
        )
        for v in options[:3]
    ]
    row2 = [
        InlineKeyboardButton(
            f"{'✅ ' if v == current else ''}{v}", callback_data=f"max_posts:{v}"
        )
        for v in options[3:]
    ]
    return InlineKeyboardMarkup([
        row1, row2,
        [InlineKeyboardButton("⬅️ Назад", callback_data="manage_settings")],
    ])
