from __future__ import annotations

import logging
import random
import time
from urllib.parse import quote_plus

from playwright.sync_api import Page, sync_playwright

from core.config import Config
from core.models import JobPost

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# All known Eluta job-card selectors, tried in order
CARD_SELECTORS = [
    "div.result",
    "li.result",
    "article.result",
    "div.job-result",
    "div[class*='job-listing']",
    "div[class*='jobListing']",
    "div[class*='job_listing']",
    "div[class*='posting']",
    "article",
]


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
            f"https://www.eluta.ca/search"
            f"?q={quote_plus(query)}"
            f"&l={quote_plus(location)}"
        )
        log.info("Fetching: %s", url)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            log.warning("Page load failed: %s", exc)
            return []

        _delay(2, 3)

        # Log page title so we can detect CAPTCHAs or error pages
        title = page.title()
        log.info("Page title: %r", title)

        # Try each card selector until one returns results
        cards = []
        for selector in CARD_SELECTORS:
            cards = page.query_selector_all(selector)
            if cards:
                log.info("Matched selector %r — %d cards", selector, len(cards))
                break

        if not cards:
            # Dump a snippet of the HTML to help debug selector mismatches
            html_snippet = page.content()[:3000]
            log.warning("No cards found for '%s' in '%s'. HTML snippet:\n%s", role, location, html_snippet)
            return []

        # --- Collect raw data from cards WITHOUT navigating away ---
        # Navigating inside _parse_card would make remaining handles stale.
        raw: list[dict] = []
        for card in cards[: self.cfg.search.max_results_per_query]:
            try:
                data = self._extract_card_data(card)
                if data:
                    raw.append(data)
            except Exception as exc:
                log.debug("Card extract error: %s", exc)

        log.info("Extracted %d raw job entries for '%s'", len(raw), role)

        # --- Build JobPost objects (eluta_url doubles as apply_url for now) ---
        jobs: list[JobPost] = []
        for d in raw:
            jobs.append(JobPost(
                title=d["title"],
                company=d.get("company", ""),
                location=d.get("location", ""),
                eluta_url=d["url"],
                apply_url=d["url"],   # user clicks through to Eluta which links to employer
                salary=d.get("salary", ""),
            ))

        return jobs

    def _extract_card_data(self, card) -> dict | None:
        """
        Pull title, URL, company, location from a card element WITHOUT
        navigating the page (so we don't invalidate sibling handles).
        """
        # Try several patterns for the job title link
        title_el = card.query_selector(
            "h2 a, h3 a, h4 a, "
            "a.jobtitle, a[class*='title'], a[class*='Title'], "
            "a[class*='job'], a[class*='Job'], "
            "a[itemprop='title'], "
            "a"   # last-resort: first anchor in card
        )
        if not title_el:
            return None

        title = (title_el.inner_text() or "").strip()
        if not title or len(title) < 3:
            return None

        href = title_el.get_attribute("href") or ""
        if not href:
            return None
        if href.startswith("/"):
            href = "https://www.eluta.ca" + href

        # Company
        company_el = card.query_selector(
            "span.company, span[class*='company'], span[class*='employer'], "
            "[class*='company'], [class*='employer'], [itemprop='hiringOrganization']"
        )
        company = (company_el.inner_text() if company_el else "").strip()

        # Location
        loc_el = card.query_selector(
            "span.location, span[class*='location'], span[class*='city'], "
            "[class*='location'], [itemprop='addressLocality']"
        )
        location = (loc_el.inner_text() if loc_el else "").strip()

        # Salary
        sal_el = card.query_selector("[class*='salary'], [class*='pay'], [class*='wage']")
        salary = (sal_el.inner_text() if sal_el else "").strip()

        return {
            "title": title,
            "url": href,
            "company": company,
            "location": location,
            "salary": salary,
        }


def _delay(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))
