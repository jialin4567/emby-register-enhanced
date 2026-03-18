"""
Report scheduler using APScheduler.
Reads REPORT_SCHEDULE env var (comma-separated: daily,weekly,monthly)
Sends via all configured channels.
"""
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _send_report(period: str):
    try:
        from reporter import build_report
        from notify import broadcast
        text = build_report(period)
        label_map = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
        results = broadcast(text, title=f"Emby {label_map.get(period, '报告')}")
        logger.info(f"Report [{period}] sent: {results}")
    except Exception as e:
        logger.error(f"Report send error [{period}]: {e}")


def start_scheduler():
    schedule_env = os.getenv("REPORT_SCHEDULE", "").strip()
    if not schedule_env:
        logger.info("REPORT_SCHEDULE not set, scheduler disabled")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error("APScheduler not installed, skipping scheduler")
        return

    periods = [p.strip().lower() for p in schedule_env.split(",") if p.strip()]
    report_hour = int(os.getenv("REPORT_HOUR", "8"))

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    if "daily" in periods:
        scheduler.add_job(
            lambda: _send_report("daily"),
            CronTrigger(hour=report_hour, minute=0),
            id="daily_report"
        )
        logger.info(f"Daily report scheduled at {report_hour}:00 CST")

    if "weekly" in periods:
        scheduler.add_job(
            lambda: _send_report("weekly"),
            CronTrigger(day_of_week="mon", hour=report_hour, minute=0),
            id="weekly_report"
        )
        logger.info(f"Weekly report scheduled Monday {report_hour}:00 CST")

    if "monthly" in periods:
        scheduler.add_job(
            lambda: _send_report("monthly"),
            CronTrigger(day=1, hour=report_hour, minute=0),
            id="monthly_report"
        )
        logger.info(f"Monthly report scheduled 1st of month {report_hour}:00 CST")

    if scheduler.get_jobs():
        scheduler.start()
        logger.info("Scheduler started")
