"""
Job Search Bot

Usage:
  python main.py              # start daemon (searches on schedule)
  python main.py search       # run one search cycle and exit
  python main.py status       # show recent jobs in terminal
  python main.py test-email   # send a test email to verify Gmail setup
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

load_dotenv()

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        RichHandler(rich_tracebacks=True, show_path=False),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)
console = Console()


def cmd_daemon(cfg) -> None:
    from agents.mediator import Mediator
    Mediator(cfg).start_daemon()


def cmd_search(cfg) -> None:
    from agents.mediator import Mediator
    Mediator(cfg).run_search_cycle()
    console.print("[green]Search cycle complete.[/green]")


def cmd_status(cfg) -> None:
    from core.database import get_recent_jobs, init_db
    init_db()
    jobs = get_recent_jobs(limit=50)
    if not jobs:
        console.print("[yellow]No jobs yet. Run: python main.py search[/yellow]")
        return

    table = Table(title="Recent Jobs", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", min_width=22)
    table.add_column("Company", min_width=14)
    table.add_column("Location", min_width=12)
    table.add_column("Seen At", width=17)

    for i, j in enumerate(jobs, 1):
        table.add_row(
            str(i), j.title, j.company or "—",
            j.location or "—",
            j.seen_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


def cmd_test_email(cfg) -> None:
    from gmail.client import GmailClient
    GmailClient(cfg).send_test_email()
    console.print(f"[green]Test email sent to {cfg.email.recipient}[/green]")


def main() -> None:
    from core.config import load_config
    cfg = load_config()

    commands = {
        "search":     cmd_search,
        "status":     cmd_status,
        "test-email": cmd_test_email,
    }

    arg = sys.argv[1] if len(sys.argv) > 1 else "daemon"

    if arg in commands:
        commands[arg](cfg)
    elif arg == "daemon":
        cmd_daemon(cfg)
    else:
        console.print(
            f"[red]Unknown command: {arg}[/red]\n"
            "Available: daemon (default), search, status, test-email"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
