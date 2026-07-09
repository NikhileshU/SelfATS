"""Common job schema — the adapter output contract every source normalizes to."""
from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha1
from typing import Literal, Optional

from pydantic import BaseModel, Field

Stage = Literal[
    "early-stage", "pre-seed", "seed", "small", "mid", "large", "mnc", "unknown"
]
ExperienceSignal = Literal["explicit_years", "skills_first", "unclear"]


class SalaryRange(BaseModel):
    min: Optional[int] = None
    max: Optional[int] = None
    currency: Optional[str] = None


class RawJob(BaseModel):
    """What an adapter hands back for a single listing, pre-dedup."""

    id: str
    title: str
    company: str
    location: Optional[str] = None
    remote: bool = False
    stage: Stage = "unknown"
    experience_signal: ExperienceSignal = "unclear"
    min_years: Optional[int] = None
    equity_mentioned: bool = False
    salary_range: SalaryRange = Field(default_factory=SalaryRange)
    url: str
    source: str
    posted_at: datetime
    raw_description: str = ""


class JobSource(BaseModel):
    source: str
    source_id: str
    url: str
    posted_at: datetime


class Job(RawJob):
    """Canonical, deduped record as stored in jobs.db and returned to tools."""

    dedup_key: str
    sources: list[JobSource] = Field(default_factory=list)
    fit_score: Optional[float] = None
    fit_rationale: Optional[str] = None
    first_seen_at: datetime
    last_seen_at: datetime


_WS_RE = re.compile(r"\s+")
_PAREN_RE = re.compile(r"\([^)]*\)")
_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_NOISE_WORDS = {
    "remote", "hybrid", "onsite", "inc", "llc", "ltd", "corp", "corporation",
    "co", "gmbh", "the",
}


def normalize_text(text: str) -> str:
    text = text.lower()
    text = _PAREN_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    words = [w for w in _WS_RE.split(text) if w and w not in _NOISE_WORDS]
    return " ".join(words)


def dedup_key_for(company: str, title: str) -> str:
    """Same role posted on multiple boards should collapse to one canonical job."""
    norm = f"{normalize_text(company)}|{normalize_text(title)}"
    return sha1(norm.encode("utf-8")).hexdigest()[:16]
