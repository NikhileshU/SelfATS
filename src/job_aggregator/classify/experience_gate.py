"""Splits listings into explicit-years-gated vs. skills/work-first vs.
unclear. Keyword+regex heuristic pass; classify/fit_score.py's LLM-assisted
pass may refine "unclear" cases on the shortlist using real judgment."""
from __future__ import annotations

import re
from typing import Optional

_EXPLICIT_YEARS_RE = re.compile(
    r"(\d{1,2})\+?\s*(?:-\s*\d{1,2}\s*)?years?\s*(?:of\s*)?"
    r"(?:relevant\s*|professional\s*|prior\s*|proven\s*)?experience",
    re.IGNORECASE,
)

_SKILLS_FIRST_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"no degree required",
        r"portfolio[- ]first",
        r"we care (?:more )?about what you can do",
        r"years of experience (?:is |are )?not required",
        r"self[- ]taught (?:welcome|friendly)",
        r"skills[- ]based hiring",
        r"we don'?t care about your resume",
        r"no prior experience (?:necessary|required|needed)",
    ]
]


def classify_experience(raw_description: str) -> tuple[str, Optional[int]]:
    match = _EXPLICIT_YEARS_RE.search(raw_description)
    if match:
        return "explicit_years", int(match.group(1))

    if any(p.search(raw_description) for p in _SKILLS_FIRST_PATTERNS):
        return "skills_first", None

    return "unclear", None
