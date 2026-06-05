from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agents.explorer import Explorer
from core.config import Config
from core.database import init_db, save_jobs
from gmail.client import GmailClient

log = logging.getLogger(__name__)


class Mediator:
    def __init__(self, config: Config):
        self.cfg = config
        self.explorer = Explorer(config)
        self.gmail = GmailClient(config)
        init_db()

    def run_search_cycle(self) -> None:
        """Find new jobs, store them, send email digest if any are new."""
        log.info("Starting search cycle")
        posts = self.explorer.search()

        if not posts:
            log.info("No jobs found this cycle")
            return

        new_count = save_jobs(posts)
        log.info("Saved %d new jobs (%d total scraped)", new_count, len(posts))

        if new_count == 0:
            log.info("All jobs already seen — no digest sent")
            return

        # Send only the newly inserted jobs
        new_posts = posts[-new_count:]
        self.gmail.send_digest(new_posts)

    def start_daemon(self) -> None:
        """Block forever, running the search cycle on schedule."""
        sched = BlockingScheduler(timezone="UTC")
        sched.add_job(
            self.run_search_cycle,
            trigger=IntervalTrigger(hours=self.cfg.schedule.search_interval_hours),
            id="search",
            max_instances=1,
            coalesce=True,
        )
        log.info(
            "Mediator daemon started — search every %dh",
            self.cfg.schedule.search_interval_hours,
        )
        self.run_search_cycle()  # run immediately on startup
        sched.start()
