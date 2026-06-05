from __future__ import annotations

import logging
import random
import time
from urllib.parse import quote_plus

from playwright.sync_api import Page, sync_playwright

from core.config import Config
from core.models import JobPost

log = logging.getLogger(__name__)

BASE_URL = "https://www.eluta.ca"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class Explorer:
    def __init__(self, config: Config):
        self.cfg = config

    def search(self) -> list[JobPost]:
        results: list[JobPost] = []
        seen_ids: set[str] = set()

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent=USER_AGENT,
                locale="en-CA",
                viewport={"width": 1280, "height": 800},
            )
            page = ctx.new_page()

            for role in self.cfg.search.roles:
                for location in self.cfg.search.locations:
                    jobs = self._search_one(page, role.name, role.keywords, location)
                    for j in jobs:
                        if j.id not in seen_ids:
                            seen_ids.add(j.id)
                            j.searched_role = role.name
                            results.append(j)
                    _delay(6, 12)

            browser.close()

        log.info("Explorer: %d unique jobs total", len(results))
        return results

    def _search_one(
        self, page: Page, role: str, keywords: list[str], location: str
    ) -> list[JobPost]:
        query = role
        if keywords:
            query = f"{role} {' '.join(keywords)}"

        url = (
            f"{BASE_URL}/search"
            f"?q={quote_plus(query)}"
            f"&l={quote_plus(location)}"
        )
        log.info("Fetching: %s", url)

        try:
            page.goto(url, wait_until="networkidle", timeout=30_000)
        except Exception as exc:
            log.warning("Page load failed: %s", exc)
            return []

        _delay(1, 2)
        log.info("Page title: %r", page.title())

        # Eluta job cards are div.organic-job
        cards = page.query_selector_all("div.organic-job")
        log.info("Found %d cards for '%s' in '%s'", len(cards), role, location)

        if not cards:
            log.warning("No cards — page snippet:\n%s", page.content()[:2000])
            return []

        jobs: list[JobPost] = []
        for card in cards[: self.cfg.search.max_results_per_query]:
            try:
                job = self._parse_card(card)
                if job:
                    jobs.append(job)
            except Exception as exc:
                log.debug("Card parse error: %s", exc)

        return jobs

    def _parse_card(self, card) -> JobPost | None:
        # --- Title ---
        title_el = card.query_selector("a.lk-job-title")
        if not title_el:
            return None
        title = (title_el.get_attribute("title") or title_el.inner_text() or "").strip()
        if not title:
            return None

        # --- URL (real path is in data-url, not href which is "#!") ---
        data_url = title_el.get_attribute("data-url") or ""
        if data_url:
            eluta_url = data_url if data_url.startswith("http") else f"{BASE_URL}/{data_url}"
        else:
            return None   # no usable link, skip card

        # --- Company ---
        company_el = card.query_selector("a.lk-employer, a.employer")
        company = (company_el.get_attribute("title") or
                   (company_el.inner_text() if company_el else "") or "").strip()
        # Strip "See all jobs at " prefix that sometimes appears in title attr
        if company.lower().startswith("see all jobs at "):
            company = company[len("see all jobs at "):].strip()

        # --- Location ---
        loc_el = card.query_selector("span.location span")
        location = (loc_el.inner_text() if loc_el else "").strip()

        # --- Salary ---
        sal_el = card.query_selector("span.position-salary")
        salary = (sal_el.inner_text() if sal_el else "").strip()
        # Collapse whitespace / newlines inside salary text
        salary = " ".join(salary.split())

        return JobPost(
            title=title,
            company=company,
            location=location,
            eluta_url=eluta_url,
            apply_url=eluta_url,
            salary=salary,
        )


def _delay(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))
