from __future__ import annotations

import base64
import json
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
from playwright.sync_api import Page, sync_playwright

from core.config import Config
from core.models import ApplicationRecord

log = logging.getLogger(__name__)

_FILL_PROMPT = """\
You are an AI assistant filling out a job application form.

A screenshot of the current page is attached.

Applicant resume data (JSON):
{resume_json}

Instructions:
1. Identify every visible form field on this page (text inputs, selects, radio buttons, checkboxes, file uploads).
2. For each field, determine the best value from the resume data.
3. Return ONLY a JSON object — no prose, no markdown fences.

JSON schema:
{{
  "fields": [
    {{
      "locator_type": "label" | "placeholder" | "css",
      "locator_value": "<text of label, placeholder, or CSS selector>",
      "fill_value": "<value to enter>",
      "field_type": "text" | "select" | "radio" | "checkbox" | "file"
    }}
  ],
  "has_next_button": true | false,
  "next_button_locator": "<text or CSS to click Next>",
  "has_submit_button": true | false,
  "submit_button_locator": "<text or CSS to click Submit>"
}}

If the page is not a job application form (e.g. login page, error page), return:
{{"not_a_form": true}}
"""


@dataclass
class FillStep:
    fields: list[dict]
    has_next: bool
    next_locator: str
    has_submit: bool
    submit_locator: str


class Filler:
    MAX_STEPS = 10

    def __init__(self, config: Config):
        self.cfg = config
        self.client = anthropic.Anthropic()
        self.resume_json = json.dumps(config.resume.as_dict(), indent=2)

    def apply_to_jobs(self, jobs) -> list[ApplicationRecord]:
        results = []
        for job in jobs:
            log.info("Applying to: %s @ %s", job.title, job.company)
            record = self.apply_to_url(job.apply_url or job.eluta_url, job.id)
            results.append(record)
            _delay(3, 6)
        return results

    def apply_to_url(self, url: str, job_id: str = "") -> ApplicationRecord:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)  # visible — safer for ATS sites
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="en-CA",
            )
            page = ctx.new_page()
            try:
                result = self._run_application(page, url, job_id)
            except Exception as exc:
                log.error("Filler error for %s: %s", url, exc)
                result = ApplicationRecord(
                    job_id=job_id, success=False, error=str(exc)
                )
            finally:
                browser.close()
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_application(self, page: Page, url: str, job_id: str) -> ApplicationRecord:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        _delay(2, 3)

        for step in range(self.MAX_STEPS):
            screenshot = page.screenshot(full_page=True)
            plan = self._ask_claude(screenshot)

            if plan is None:
                return ApplicationRecord(
                    job_id=job_id,
                    success=False,
                    error="Claude could not parse the form",
                )

            if plan.get("not_a_form"):
                log.warning("Step %d: not a form page at %s", step, page.url)
                return ApplicationRecord(
                    job_id=job_id,
                    success=False,
                    error="Page is not a job application form",
                )

            fill_step = self._parse_plan(plan)
            self._execute_fill(page, fill_step)
            _delay(1, 2)

            if fill_step.has_submit:
                self._click(page, fill_step.submit_locator)
                _delay(2, 3)
                log.info("Submitted application for job_id=%s", job_id)
                return ApplicationRecord(
                    job_id=job_id,
                    success=True,
                    ats_detected=self._detect_ats(page.url),
                )

            if fill_step.has_next:
                self._click(page, fill_step.next_locator)
                _delay(1, 2)
            else:
                # No next and no submit — form may be complete or stuck
                break

        return ApplicationRecord(
            job_id=job_id,
            success=False,
            error="Reached max steps without submitting",
        )

    def _ask_claude(self, screenshot_bytes: bytes) -> dict | None:
        img_b64 = base64.standard_b64encode(screenshot_bytes).decode()
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": _FILL_PROMPT.format(resume_json=self.resume_json),
                        },
                    ],
                }],
            )
            raw = response.content[0].text.strip()
            # Strip accidental markdown fences
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(raw)
        except Exception as exc:
            log.warning("Claude API error: %s", exc)
            return None

    def _parse_plan(self, plan: dict) -> FillStep:
        return FillStep(
            fields=plan.get("fields", []),
            has_next=bool(plan.get("has_next_button")),
            next_locator=plan.get("next_button_locator", ""),
            has_submit=bool(plan.get("has_submit_button")),
            submit_locator=plan.get("submit_button_locator", ""),
        )

    def _execute_fill(self, page: Page, step: FillStep) -> None:
        for field in step.fields:
            try:
                self._fill_field(page, field)
            except Exception as exc:
                log.debug("Could not fill field %s: %s", field.get("locator_value"), exc)

    def _fill_field(self, page: Page, field: dict) -> None:
        ltype = field.get("locator_type", "label")
        lvalue = field.get("locator_value", "")
        value = str(field.get("fill_value", ""))
        ftype = field.get("field_type", "text")

        if ltype == "label":
            locator = page.get_by_label(lvalue, exact=False)
        elif ltype == "placeholder":
            locator = page.get_by_placeholder(lvalue, exact=False)
        else:
            locator = page.locator(lvalue)

        if ftype == "file":
            pdf = self.cfg.resume.resume_pdf_path
            if pdf and Path(pdf).exists():
                locator.set_input_files(pdf)
            return

        if ftype == "select":
            try:
                locator.select_option(label=value)
            except Exception:
                locator.select_option(value=value)
            return

        if ftype in ("radio", "checkbox"):
            # Find the option matching our value and click it
            page.locator(f"[value='{value}']").first.check()
            return

        # Default: text input
        locator.fill(value)

    def _click(self, page: Page, locator_str: str) -> None:
        if not locator_str:
            return
        try:
            page.get_by_role("button", name=locator_str, exact=False).first.click()
        except Exception:
            page.locator(locator_str).first.click()

    def _detect_ats(self, url: str) -> str:
        url_lower = url.lower()
        for name in ("workday", "greenhouse", "lever", "taleo", "bamboo", "rippling", "icims"):
            if name in url_lower:
                return name
        return "unknown"


def _delay(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))
