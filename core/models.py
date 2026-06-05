from __future__ import annotations

import hashlib
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from pydantic import BaseModel, Field


class JobPost(BaseModel):
    id: str = Field(default="")
    title: str
    company: str
    location: str
    eluta_url: str
    apply_url: str
    salary: str = ""
    searched_role: str = ""
    seen_at: datetime = Field(default_factory=datetime.utcnow)
    batch_id: str = ""

    def model_post_init(self, __context) -> None:
        if not self.id:
            parts = urlsplit(self.apply_url or self.eluta_url)
            canonical = urlunsplit((
                parts.scheme.lower(), parts.netloc.lower(),
                parts.path.rstrip("/"), "", ""
            ))
            self.id = hashlib.sha1(canonical.encode()).hexdigest()


class EmailBatch(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    gmail_thread_id: str = ""
    sent_at: datetime = Field(default_factory=datetime.utcnow)
    job_ids: list[str] = Field(default_factory=list)
    replied: bool = False
    reply_received_at: datetime | None = None


class ApplicationRecord(BaseModel):
    job_id: str
    attempted_at: datetime = Field(default_factory=datetime.utcnow)
    success: bool
    ats_detected: str = ""
    error: str = ""


class ReplyMessage(BaseModel):
    thread_id: str
    message_id: str
    body: str
    received_at: datetime
