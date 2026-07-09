from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CVRole(BaseModel):
    title: str
    company: Optional[str] = None
    date_range: Optional[str] = None
    duration_years: Optional[float] = None


class CVProfile(BaseModel):
    raw_text: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    total_years_experience: Optional[float] = None
    roles: list[CVRole] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    summary: Optional[str] = None
    updated_at: datetime
