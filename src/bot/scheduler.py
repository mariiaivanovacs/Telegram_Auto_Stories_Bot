"""APScheduler setup — isolated so it can be swapped for Cloud Scheduler later."""
from __future__ import annotations

import asyncio
import logging

import pytz

import src.db as db

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except Exception:
    AsyncIOScheduler = None

try:
    from telegram.ext import Application
except Exception:
    Application = None

_JOB_ID = "daily_run"


async def _scheduled_run() -> None:
    logger.info("Scheduled daily run triggered")
    from src.main import run_pipeline
    from src.sender import send_to_admins

    def progress(msg: str) -> None:
        send_to_admins(msg)

    await asyncio.to_thread(run_pipeline, progress)


async def setup(application: Application, run_time: str, timezone: str) -> None:
    if AsyncIOScheduler is None:
        logger.warning("APScheduler not installed — scheduled daily runs disabled.")
        return

    tz = pytz.timezone(timezone)
    time_str = db.get_schedule_time(default=run_time)
    hour, minute = map(int, time_str.split(":"))

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        _scheduled_run,
        trigger="cron",
        hour=hour,
        minute=minute,
        id=_JOB_ID,
    )
    scheduler.start()
    application.bot_data["scheduler"] = scheduler
    logger.info("Scheduler: daily run at %s %s", time_str, timezone)


async def reschedule(application: Application, run_time: str, timezone: str) -> None:
    """Update the daily job with a new time without restarting the scheduler."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler is None or not scheduler.running:
        await setup(application, run_time, timezone)
        return

    tz = pytz.timezone(timezone)
    hour, minute = map(int, run_time.split(":"))
    scheduler.reschedule_job(
        _JOB_ID,
        trigger="cron",
        hour=hour,
        minute=minute,
        timezone=tz,
    )
    logger.info("Scheduler rescheduled: daily at %s %s", run_time, timezone)


async def teardown(application: Application) -> None:
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
