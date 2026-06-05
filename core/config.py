from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel


class ScheduleConfig(BaseModel):
    search_interval_hours: int = 3
    reply_poll_minutes: int = 5


class RoleConfig(BaseModel):
    name: str
    keywords: list[str] = []


class SearchConfig(BaseModel):
    roles: list[RoleConfig] = []
    locations: list[str] = ["Remote"]
    max_results_per_query: int = 20


class EmailConfig(BaseModel):
    recipient: str
    subject_prefix: str = "[Job Bot]"


class ResumeConfig(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    province: str = ""
    country: str = "Canada"
    linkedin_url: str = ""
    resume_pdf_path: str = ""
    legally_authorized: bool = True
    requires_sponsorship: bool = False
    years_experience: int = 0

    def as_dict(self) -> dict:
        return self.model_dump()


class Config(BaseModel):
    schedule: ScheduleConfig = ScheduleConfig()
    search: SearchConfig = SearchConfig()
    email: EmailConfig
    resume: ResumeConfig = ResumeConfig()


def load_config(path: str | Path = "config.yaml") -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config(**data)
