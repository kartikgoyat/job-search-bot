from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, String, Text, create_engine
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from core.models import ApplicationRecord, EmailBatch, JobPost

DB_PATH = Path("jobs.db")
_engine = None
_Session = None


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    id          = Column(String, primary_key=True)
    title       = Column(String, nullable=False)
    company     = Column(String, default="")
    location    = Column(String, default="")
    eluta_url   = Column(String, default="")
    apply_url   = Column(String, default="")
    salary        = Column(String, default="")
    searched_role = Column(String, default="")
    seen_at       = Column(DateTime, default=datetime.utcnow)
    batch_id      = Column(String, default="")
    applied     = Column(Boolean, default=False)
    applied_at  = Column(DateTime, nullable=True)


class BatchRow(Base):
    __tablename__ = "email_batches"

    id              = Column(String, primary_key=True)
    gmail_thread_id = Column(String, default="", index=True)
    sent_at         = Column(DateTime, default=datetime.utcnow)
    job_ids_json    = Column(Text, default="[]")
    replied         = Column(Boolean, default=False)
    reply_received_at = Column(DateTime, nullable=True)


class ApplicationRow(Base):
    __tablename__ = "applications"

    id           = Column(String, primary_key=True)
    job_id       = Column(String, ForeignKey("jobs.id"), nullable=False)
    attempted_at = Column(DateTime, default=datetime.utcnow)
    success      = Column(Boolean, default=False)
    ats_detected = Column(String, default="")
    error        = Column(Text, default="")


def init_db(path: Path = DB_PATH) -> None:
    global _engine, _Session
    _engine = create_engine(f"sqlite:///{path}", echo=False)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(bind=_engine)


def _session() -> Session:
    if _Session is None:
        init_db()
    return _Session()


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def save_jobs(posts: list[JobPost]) -> int:
    inserted = 0
    with _session() as s:
        for p in posts:
            if not s.get(JobRow, p.id):
                s.add(JobRow(
                    id=p.id, title=p.title, company=p.company,
                    location=p.location, eluta_url=p.eluta_url,
                    apply_url=p.apply_url, salary=p.salary,
                    searched_role=p.searched_role,
                    seen_at=p.seen_at, batch_id=p.batch_id,
                ))
                inserted += 1
        s.commit()
    return inserted


def get_recent_jobs(limit: int = 50) -> list[JobRow]:
    with _session() as s:
        return (
            s.query(JobRow)
            .order_by(JobRow.seen_at.desc())
            .limit(limit)
            .all()
        )


def get_jobs_by_ids(ids: list[str]) -> list[JobRow]:
    with _session() as s:
        return s.query(JobRow).filter(JobRow.id.in_(ids)).all()


def mark_applied(job_id: str, record: ApplicationRecord) -> None:
    from uuid import uuid4
    with _session() as s:
        row = s.get(JobRow, job_id)
        if row:
            row.applied = True
            row.applied_at = record.attempted_at
        s.add(ApplicationRow(
            id=uuid4().hex,
            job_id=job_id,
            attempted_at=record.attempted_at,
            success=record.success,
            ats_detected=record.ats_detected,
            error=record.error,
        ))
        s.commit()


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

def create_batch(job_ids: list[str]) -> BatchRow:
    from uuid import uuid4
    row = BatchRow(
        id=uuid4().hex,
        job_ids_json=json.dumps(job_ids),
        sent_at=datetime.utcnow(),
    )
    with _session() as s:
        s.add(row)
        s.commit()
        s.refresh(row)
    return row


def save_thread_id(batch_id: str, thread_id: str) -> None:
    with _session() as s:
        row = s.get(BatchRow, batch_id)
        if row:
            row.gmail_thread_id = thread_id
            s.commit()


def get_batch_by_thread(thread_id: str) -> Optional[BatchRow]:
    with _session() as s:
        return (
            s.query(BatchRow)
            .filter(BatchRow.gmail_thread_id == thread_id)
            .first()
        )


def get_active_thread_ids() -> list[str]:
    """Return thread IDs for batches not yet replied to."""
    with _session() as s:
        rows = (
            s.query(BatchRow)
            .filter(BatchRow.replied == False, BatchRow.gmail_thread_id != "")
            .all()
        )
        return [r.gmail_thread_id for r in rows]


def mark_batch_replied(batch_id: str) -> None:
    with _session() as s:
        row = s.get(BatchRow, batch_id)
        if row:
            row.replied = True
            row.reply_received_at = datetime.utcnow()
            s.commit()
