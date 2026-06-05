from __future__ import annotations

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from core.config import Config

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class GmailClient:
    def __init__(self, config: Config):
        self.cfg = config
        self._user = os.environ["GMAIL_USER"]
        self._password = os.environ["GMAIL_APP_PASSWORD"]

    def send_digest(self, jobs: list) -> None:
        """Send an HTML job digest email. No return value needed."""
        if not jobs:
            return

        roles_str = ", ".join(self.cfg.search.roles)
        subject = (
            f"{self.cfg.email.subject_prefix} "
            f"{len(jobs)} new job{'s' if len(jobs) != 1 else ''} "
            f"— {roles_str}"
        )
        html = self._render_digest(jobs)
        text = self._plain_digest(jobs)
        self._send(subject, html, text)
        log.info("Digest sent: %d jobs to %s", len(jobs), self.cfg.email.recipient)

    def send_test_email(self) -> None:
        self._send(
            subject=f"{self.cfg.email.subject_prefix} Connection test — OK",
            html="<p>Job Bot is connected and sending emails correctly.</p>",
            text="Job Bot is connected and sending emails correctly.",
        )
        log.info("Test email sent to %s", self.cfg.email.recipient)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, subject: str, html: str, text: str) -> None:
        msg = MIMEMultipart("alternative")
        msg["From"] = self._user
        msg["To"] = self.cfg.email.recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(self._user, self._password)
            server.send_message(msg)

    def _render_digest(self, jobs: list) -> str:
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=True,
        )
        return env.get_template("digest.html.j2").render(
            jobs=jobs,
            roles=self.cfg.search.roles,
            generated_at=datetime.utcnow(),
        )

    def _plain_digest(self, jobs: list) -> str:
        lines = [f"New jobs for: {self.cfg.search.role}\n"]
        for i, j in enumerate(jobs, 1):
            lines.append(f"#{i}  {j.title} @ {j.company}  ({j.location})")
            apply = j.apply_url or j.eluta_url
            lines.append(f"     Apply: {apply}\n")
        return "\n".join(lines)
