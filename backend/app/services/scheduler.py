from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import Settings


def build_scheduler(settings: Settings, crawl_job: Callable[[], Awaitable[None]]) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(crawl_job, CronTrigger(hour=settings.crawl_hour, minute=settings.crawl_minute), id="daily_crawl", replace_existing=True)
    return scheduler
