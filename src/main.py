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
from src.sender import send_all, send_to_chat_markup
from src.story import generate_stories

logger = logging.getLogger(__name__)

_LOG_DIR = Path("logs")
_LOG_FILE = _LOG_DIR / "app.log"


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


def run_pipeline(progress_cb=None) -> None:
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

    def _notify(msg: str) -> None:
        logger.info(msg)
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception as exc:
                logger.warning("Progress callback error: %s", exc)

    if not lock.acquire():
        logger.warning("Pipeline skipped — another run is already in progress")
        _notify("⚠️ A run is already in progress; skipped.")
        return

    db.init(settings)  # ensure schema + channels/products seeded before every run

    run_id = db.create_run()
    logger.info("── Run #%d started ──────────────────────────────────────", run_id)
    n_channels = len(settings.channels)
    _notify(
        f"🔍 Scanning {n_channels} competitor channel{'s' if n_channels != 1 else ''}"
        " for recent prices..."
    )

    try:
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
            unavailable = [ch.username for ch in settings.channels]

        for ch in unavailable:
            errors.append(f"Channel unavailable: {ch}")

        _notify(f"📥 {len(messages)} messages collected. Finding prices...")

        # ── 2. Match products → prices ──────────────────────────────────────
        match_results = match_products(messages, settings.products)

        n_found = sum(1 for v in match_results.values() if v["min_price"] is not None)
        n_total = len(settings.products)

        if n_found == 0 and messages:
            logger.critical("0 prices found across %d messages", len(messages))
            errors.append("0 prices found")
            _notify("⚠️ No prices found — channel format may have changed.")

        _notify(f"💰 Found prices for {n_found}/{n_total} products.")

        # ── 3. Calculate prices + persist ───────────────────────────────────
        db_products = db.get_all_products()
        price_results = calculate_prices(
            match_results,
            db_products,
            discount=db.get_pricing_discount(settings.pricing.discount),
            large_change_threshold=settings.pricing.large_change_threshold,
        )

        for r in price_results:
            if not r["price_kept"] and r["is_large_change"]:
                change_id = db.create_pending_price_change(
                    run_id=run_id,
                    product_id=r["db_id"],
                    proposed_price=r["calculated_price"],
                    old_price=r["old_price"],
                )
                for admin in settings.admins:
                    send_to_chat_markup(
                        admin.telegram_id,
                        "Large price change needs confirmation\n"
                        f"{r['canonical_name']}\n"
                        f"Old: {r['old_price']}\n"
                        f"New: {r['calculated_price']}\n"
                        f"Delta: {r['price_delta']}",
                        {
                            "inline_keyboard": [[
                                {"text": "ДА", "callback_data": f"approve_price_{change_id}"},
                                {"text": "написать свою цену", "callback_data": f"manual_price_{change_id}"},
                            ]]
                        },
                    )
                errors.append(f"Pending admin confirmation: {r['canonical_name']}")
                r["calculated_price"] = r["old_price"]
                r["price_kept"] = True

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

        # ── 4. Build texts ──────────────────────────────────────────────────
        price_list_text = build_price_list(price_results, settings.price_list_template)
        channel_names = [ch.username for ch in settings.channels]
        report_text = build_report(
            price_results, unavailable, channel_names, started_at, errors
        )

        # ── 5. Generate story images ────────────────────────────────────────
        _notify("🎨 Creating story images...")
        story_paths: list[str] = []
        try:
            story_paths = generate_stories(price_results, settings.story)
        except Exception as exc:
            logger.error("Story generation failed: %s", exc, exc_info=True)
            errors.append(f"Story generation failed: {exc}")
            _notify(f"⚠️ Story images failed: {exc}")

        # ── 6. Deliver to admins ────────────────────────────────────────────
        n_stories = len(story_paths)
        _notify(
            f"📤 Sending price list and "
            f"{n_stories} story image{'s' if n_stories != 1 else ''} to you..."
        )
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
        _notify(
            f"{status_emoji} Done — {n_priced}/{n_total} prices updated "
            f"in {duration:.0f}s."
        )

    except Exception as exc:
        logger.critical("Unhandled exception in pipeline: %s", exc, exc_info=True)
        db.finish_run(run_id, "failed", 0, len(db.get_all_products()), [str(exc)])
        _notify(f"❌ Pipeline crashed: {exc}")
        raise

    finally:
        lock.release()


if __name__ == "__main__":
    run_pipeline()
