from __future__ import annotations

import logging
import random
import time
from urllib.parse import quote_plus, urlsplit

from playwright.sync_api import Page, sync_playwright

from core.config import Config
from core.models import JobPost

log = logging.getLogger(__name__)

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
                    jobs = self._search_one(page, role, location)
                    for j in jobs:
                        if j.id not in seen_ids:
                            seen_ids.add(j.id)
                            j.searched_role = role
                            results.append(j)
                    _delay(6, 12)

            browser.close()

        log.info("Explorer found %d unique jobs", len(results))
        return results

    def _search_one(self, page: Page, role: str, location: str) -> list[JobPost]:
        url = (
            f"https://www.eluta.ca/search"
            f"?q={quote_plus(role)}"
            f"&l={quote_plus(location)}"
        )
        log.info("Searching: %s", url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except Exception as exc:
            log.warning("Page load failed for %s: %s", url, exc)
            return []

        _delay(2, 4)

        jobs: list[JobPost] = []
        cards = page.query_selector_all("div.result, div.job-result, li.result")

        if not cards:
            # Fallback: try generic job card selectors
            cards = page.query_selector_all("[class*='result']")

        log.info("Found %d cards for '%s' in '%s'", len(cards), role, location)

        for card in cards[: self.cfg.search.max_results_per_query]:
            try:
                job = self._parse_card(card, page)
                if job:
                    jobs.append(job)
            except Exception as exc:
                log.debug("Card parse error: %s", exc)
            _delay(0.3, 0.8)

        return jobs

    def _parse_card(self, card, page: Page) -> JobPost | None:
        # Title and eluta URL
        title_el = card.query_selector("a.jobtitle, a[class*='title'], h2 a, h3 a, a")
        if not title_el:
            return None

        title = (title_el.inner_text() or "").strip()
        if not title:
            return None

        href = title_el.get_attribute("href") or ""
        if href.startswith("/"):
            href = "https://www.eluta.ca" + href
        eluta_url = href

        # Company
        company_el = card.query_selector(
            "span.company, [class*='company'], [class*='employer']"
        )
        company = (company_el.inner_text() if company_el else "").strip()

        # Location
        loc_el = card.query_selector(
            "span.location, [class*='location'], [class*='city']"
        )
        location = (loc_el.inner_text() if loc_el else "").strip()

        # Salary (optional)
        sal_el = card.query_selector("[class*='salary'], [class*='pay']")
        salary = (sal_el.inner_text() if sal_el else "").strip()

        # Resolve apply_url by following the eluta listing page
        apply_url = self._resolve_apply_url(page, eluta_url) or eluta_url

        return JobPost(
            title=title,
            company=company,
            location=location,
            eluta_url=eluta_url,
            apply_url=apply_url,
            salary=salary,
        )

    def _resolve_apply_url(self, page: Page, eluta_url: str) -> str | None:
        """
        Visit the Eluta listing page and extract the employer's direct apply link.
        Returns None if we can't resolve it (caller falls back to eluta_url).
        """
        if not eluta_url or not eluta_url.startswith("http"):
            return None
        try:
            page.goto(eluta_url, wait_until="domcontentloaded", timeout=20_000)
            _delay(1, 2)

            # Look for an "Apply" button / link pointing to an external site
            apply_el = page.query_selector(
                "a[class*='apply'], a#apply-button, a[href*='apply'], "
                "a[class*='Apply'], button[class*='apply']"
            )
            if apply_el:
                href = apply_el.get_attribute("href") or ""
                if href.startswith("http") and "eluta.ca" not in href:
                    return href

            # Fallback: any outbound link labelled "Apply" or "Apply Now"
            for a in page.query_selector_all("a"):
                text = (a.inner_text() or "").strip().lower()
                if text in ("apply", "apply now", "apply online"):
                    href = a.get_attribute("href") or ""
                    if href.startswith("http") and "eluta.ca" not in href:
                        return href

        except Exception as exc:
            log.debug("Could not resolve apply URL for %s: %s", eluta_url, exc)

        return None


def _delay(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))
