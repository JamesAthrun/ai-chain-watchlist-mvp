"""APScheduler-based job scheduler."""

import logging
import os
import sys

from dotenv import load_dotenv

# Add parent path for module imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

load_dotenv()

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.bot.commands import handle_summary
from app.core.config_loader import get_all_tickers

logger = logging.getLogger(__name__)


def send_telegram_message(text: str, chat_id: str, token: str):
    """Send a message via Telegram Bot API."""
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Split long messages
    max_len = 4096
    chunks = []
    if len(text) <= max_len:
        chunks = [text]
    else:
        lines = text.split("\n")
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > max_len:
                chunks.append(chunk)
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk.strip():
            chunks.append(chunk)

    for chunk in chunks:
        try:
            resp = requests.post(
                url,
                json={"chat_id": chat_id, "text": chunk},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f"Telegram send failed: {resp.status_code} {resp.text}")
        except Exception as e:
            logger.warning(f"Telegram send error: {e}")


def scheduled_report_job():
    """Generate and send market report."""
    logger.info("Running scheduled report job...")

    try:
        report = handle_summary()
    except Exception as e:
        logger.error(f"Scheduled report generation failed: {e}")
        report = f"定时报告生成失败: {e}"

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if token and chat_id:
        send_telegram_message(report, chat_id, token)
        logger.info("Report sent to Telegram.")
    else:
        print("=" * 40)
        print("SCHEDULED REPORT (Telegram not configured)")
        print("=" * 40)
        print(report)
        print("=" * 40)


def scheduled_global_market_job():
    """Fetch and save global market snapshot."""
    from app.core.global_market import save_snapshot
    logger.info("Running scheduled global market snapshot job...")
    try:
        data = save_snapshot()
        count = len([m for m in data.get("markets", []) if m.get("price") is not None])
        logger.info(f"Global market snapshot saved: {count} tickers with data")
    except Exception as e:
        logger.error(f"Global market snapshot failed: {e}")


def main():
    """Start the scheduler."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. "
            "Reports will be printed to console."
        )

    scheduler = BlockingScheduler()

    # Run market report every 30 minutes
    scheduler.add_job(
        scheduled_report_job,
        trigger=IntervalTrigger(minutes=30),
        id="market_report",
        name="Market Report",
        replace_existing=True,
    )

    # Global market snapshot: 08:00 CST (00:00 UTC) - captures US/EU close
    scheduler.add_job(
        scheduled_global_market_job,
        trigger=CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="global_market_morning",
        name="Global Market Morning Snapshot",
        replace_existing=True,
    )

    # Global market snapshot: 18:00 CST (10:00 UTC) - captures Asia close
    scheduler.add_job(
        scheduled_global_market_job,
        trigger=CronTrigger(hour=10, minute=0, timezone="UTC"),
        id="global_market_evening",
        name="Global Market Evening Snapshot",
        replace_existing=True,
    )

    print("Scheduler started. Report every 30 minutes. Global market at 08:00/18:00 CST.")
    print("Press Ctrl+C to stop.")

    # Run once immediately
    scheduled_report_job()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Scheduler stopped.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    main()
