"""
Pipeline orchestrator.
Called by the scheduler, by bot.py trigger, or directly:
  python -m src.main
"""
import logging
import logging.handlers
import time
from datetime import datetime, timezone
from pathlib import Path

import src.db as db
import src.lock as lock
from src.config import get_settings
from src.fetcher import fetch_messages, NotAuthenticatedError
from src.matcher import match_products
from src.pricing import calculate_prices
from src.report import build_price_list, build_report
from src.sender import send_all
from src.story import generate_stories

logger = logging.getLogger(__name__)

_LOG_DIR = Path("logs")
_LOG_FILE = _LOG_DIR / "app.log"
_APPROVAL_POLL_SECONDS = 2
_APPROVAL_TIMEOUT_SECONDS = 60 * 60 * 4


def setup_logging() -> None:
    if logging.getLogger().handlers:
        return  # already configured (e.g. called from bot thread)

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)


def run_pipeline(progress_cb=None, wait_chat_id: int | None = None) -> None:
    """
    Execute the full daily pipeline:
      fetch → match → price → report → stories → deliver → persist

    progress_cb: optional callable(str) → sends status messages to the admin
                 who triggered the run (or to all admins for scheduled runs).
    """
    setup_logging()
    settings = get_settings()
    t0 = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    errors: list[str] = []
    unavailable: list[str] = []
    run_id: int | None = None

    def _notify(msg: str) -> None:
        logger.info(msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception as exc:
                logger.warning("Progress callback error: %s", exc)

    class _Cancelled(Exception):
        pass

    def _check_cancel() -> None:
        if lock.is_cancelled():
            raise _Cancelled

    if not lock.acquire():
        logger.warning("Pipeline skipped — another run is already in progress")
        _notify("⚠️ Запуск уже выполняется — пропущено.")
        return

    try:
        db.init(settings)  # ensure schema + channels/products seeded before every run

        channels = db.get_active_channels()
        if not channels:
            logger.warning("Pipeline skipped — no active competitor channels configured")
            _notify("⚠️ Нет активных каналов конкурентов. Добавьте канал через панель управления.")
            return

        run_id = db.create_run()
        logger.info("── Run #%d started ──────────────────────────────────────", run_id)
        n_channels = len(channels)
        _notify(f"🔍 Сканирую {n_channels} канал(а) конкурентов...")

        # ── 1. Fetch messages ───────────────────────────────────────────────
        try:
            messages, unavailable = fetch_messages(run_id, progress_cb=_notify)
        except NotAuthenticatedError as exc:
            logger.error("Userbot not authenticated: %s", exc)
            _notify(f"🔐 {exc}\nUse /auth in this chat to authenticate the userbot.")
            db.finish_run(run_id, "failed", 0, len(settings.products), [str(exc)])
            return
        except Exception as exc:
            logger.critical("Fetch stage crashed: %s", exc, exc_info=True)
            errors.append(f"Fetch failed: {exc}")
            messages = []
            unavailable = [ch["username"] for ch in channels]

        for ch in unavailable:
            errors.append(f"Channel unavailable: {ch}")

        _notify(f"📥 Собрано {len(messages)} сообщений. Ищу цены...")
        _check_cancel()

        # ── 2. Match products → prices ──────────────────────────────────────
        match_results = match_products(messages, settings.products)

        n_found = sum(1 for v in match_results.values() if v["min_price"] is not None)
        n_total = len(settings.products)

        if n_found == 0 and messages:
            logger.critical("0 prices found across %d messages", len(messages))
            errors.append("0 prices found")
            _notify("⚠️ Цены не найдены — возможно, изменился формат сообщений в каналах.")

        _notify(f"💰 Найдено цен: {n_found}/{n_total}.")
        _check_cancel()

        # ── 3. Calculate prices + persist ───────────────────────────────────
        db_products = db.get_all_products()
        price_results = calculate_prices(
            match_results,
            db_products,
            discount=db.get_pricing_discount(settings.pricing.discount),
            large_change_threshold=settings.pricing.large_change_threshold,
        )

        for r in price_results:
            if not r["price_kept"]:
                db.update_product_price(r["db_id"], r["calculated_price"])
            db.write_price_history(
                run_id=run_id,
                product_id=r["db_id"],
                competitor_price=r["competitor_price"],
                source_channel=r["source_channel"],
                calculated_price=r["calculated_price"],
                price_delta=r["price_delta"],
                is_large_change=r["is_large_change"],
                price_kept=r["price_kept"],
            )

        _check_cancel()

        # ── 4. Build texts ──────────────────────────────────────────────────
        price_list_text = build_price_list(price_results, settings.price_list_template)
        channel_names = [ch["username"] for ch in channels]
        report_text = build_report(
            price_results, unavailable, channel_names, started_at, errors
        )

        _check_cancel()

        # ── 5. Generate story images ────────────────────────────────────────
        _notify("🎨 Создаю сторис...")
        story_paths: list[str] = []
        try:
            story_paths = generate_stories(price_results, settings.story, design=db.get_story_design())
        except Exception as exc:
            logger.error("Story generation failed: %s", exc, exc_info=True)
            errors.append(f"Story generation failed: {exc}")
            _notify(f"⚠️ Ошибка генерации сторис: {exc}")

        # ── 6. Deliver to admins ────────────────────────────────────────────
        n_stories = len(story_paths)
        _notify(f"📤 Отправляю прайс и {n_stories} сторис...")
        try:
            delivery_errors = send_all(price_list_text, report_text, story_paths)
            errors.extend(delivery_errors)
        except Exception as exc:
            logger.error("Delivery failed: %s", exc, exc_info=True)
            errors.append(f"Delivery failed: {exc}")

        # ── 7. Finalise run record ──────────────────────────────────────────
        n_priced = sum(1 for r in price_results if not r["price_kept"])
        n_missing = sum(1 for r in price_results if r["price_kept"])
        status = "success" if not errors else ("partial" if n_priced > 0 else "failed")
        db.finish_run(run_id, status, n_priced, n_missing, errors)

        duration = time.monotonic() - t0
        missing_names = ", ".join(
            r["canonical_name"] for r in price_results if r["price_kept"]
        ) or "none"
        logger.info(
            "RUN COMPLETE | found=%d/%d | missing=%s | duration=%.1fs | status=%s",
            n_priced, len(price_results), missing_names, duration, status,
        )

        status_emoji = "✅" if status == "success" else ("⚠️" if status == "partial" else "❌")
        _notify(f"{status_emoji} Готово — {n_priced}/{n_total} цен обновлено за {duration:.0f}с.")

    except _Cancelled:
        logger.info("Pipeline cancelled by /stop command")
        if run_id is not None:
            db.finish_run(run_id, "cancelled", 0, len(db.get_all_products()), ["Отменено командой /stop"])
        _notify("🛑 Пайплайн остановлен.")

    except Exception as exc:
        logger.critical("Unhandled exception in pipeline: %s", exc, exc_info=True)
        if run_id is not None:
            db.finish_run(run_id, "failed", 0, len(db.get_all_products()), [str(exc)])
        _notify(f"❌ Pipeline crashed: {exc}")
        raise

    finally:
        lock.release()


def _wait_for_price_approvals(run_id: int, notify) -> bool:
    deadline = time.monotonic() + _APPROVAL_TIMEOUT_SECONDS
    last_unresolved: int | None = None

    while time.monotonic() < deadline:
        unresolved = db.count_unresolved_price_changes_for_run(run_id)
        if unresolved == 0:
            return True
        if unresolved != last_unresolved:
            logger.info("Waiting for %d unresolved price approval(s)", unresolved)
            last_unresolved = unresolved
        lock.refresh()
        time.sleep(_APPROVAL_POLL_SECONDS)

    return db.count_unresolved_price_changes_for_run(run_id) == 0


def _apply_resolved_price_changes(
    run_id: int,
    pending_results_by_change_id: dict[int, dict],
    errors: list[str],
) -> None:
    changes = {
        change["id"]: change
        for change in db.get_price_changes_for_run(run_id)
        if change["id"] in pending_results_by_change_id
    }

    for change_id, result in pending_results_by_change_id.items():
        change = changes.get(change_id)
        status = change["status"] if change else "missing"
        old_price = result.get("old_price")

        if status == "approved":
            final_price = change["proposed_price"]
            price_kept = False
        elif status == "manual" and change.get("manual_price") is not None:
            final_price = change["manual_price"]
            price_kept = False
            result["price_delta"] = (
                final_price - old_price if old_price is not None else 0
            )
            default_price = result.get("default_price")
            result["default_delta"] = (
                final_price - default_price if default_price is not None else None
            )
        else:
            final_price = old_price
            price_kept = True
            if status in {"pending", "awaiting_manual"}:
                errors.append(f"Unresolved price confirmation: {result['canonical_name']}")

        result["calculated_price"] = final_price
        result["price_kept"] = price_kept

        db.write_price_history(
            run_id=run_id,
            product_id=result["db_id"],
            competitor_price=result["competitor_price"],
            source_channel=result["source_channel"],
            calculated_price=final_price,
            price_delta=result["price_delta"],
            is_large_change=result["is_large_change"],
            price_kept=price_kept,
        )


def _format_large_change_confirmation(result: dict, match: dict) -> str:
    lines = [
        "⚠️ Крупное изменение цены — требуется подтверждение",
        result["canonical_name"],
        f"Канал конкурента: @{result.get('source_channel') or match.get('source_channel') or '—'}",
        f"Цена конкурента: {_fmt_money(result.get('competitor_price'))}",
        f"Старая цена: {_fmt_money(result['old_price'])}",
        f"Новая цена: {_fmt_money(result['calculated_price'])}",
        f"Разница: {_fmt_delta(result['price_delta'])}",
    ]
    matched_lines = match.get("matched_lines") or []
    if matched_lines:
        lines.append("")
        lines.append("Совпавшие строки:")
        for item in matched_lines[:3]:
            original = (item.get("original_text") or item.get("text") or "").strip()
            if len(original) > 180:
                original = original[:177].rstrip() + "..."
            lines.append(f'@{item["channel"]}: "{original}" → {_fmt_money(item["price"])}')
    return "\n".join(lines)


def _fmt_money(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", " ") + " ₽"


def _fmt_delta(value: int | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,}".replace(",", " ") + " ₽"


if __name__ == "__main__":
    run_pipeline()
