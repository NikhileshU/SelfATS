from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ApplicationDraft(BaseModel):
    job_id: str
    job_title: str
    company: str
    url: str
    resume_emphasis: list[str]
    cover_note: str
    generated_via: Literal["llm", "heuristic"]
