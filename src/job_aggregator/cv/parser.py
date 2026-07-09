"""Heuristic CV structuring: pulls contact info, roles, skills, tools, and
companies out of raw CV text via regex/keyword matching — no LLM call.

This is intentionally the "cheap heuristic" half of the ADR's hybrid
philosophy, not the LLM-assisted half (that's reserved for
classify/fit_score.py's shortlist judgment, which needs nuance heuristics
can't give). raw_text is always kept in full on the profile so downstream
scoring can fall back to it regardless of how well a given resume's
formatting parses here.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from job_aggregator.cv.models import CVProfile, CVRole

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{3,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?", re.IGNORECASE)

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*"
_DATE_TOKEN = rf"(?:{_MONTH}\d{{4}}|\d{{4}})"
_DATE_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN})\s*(?:-|–|—|to)\s*(?P<end>{_DATE_TOKEN}|Present|Current|Now)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\d{4}")
_EXPLICIT_YEARS_RE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\+?\s*years?\s*(?:of\s*)?experience", re.IGNORECASE
)

_SECTION_HEADERS = [
    "summary", "objective", "profile",
    "experience", "work experience", "employment history", "professional experience",
    "skills", "technical skills", "core skills",
    "education",
    "projects",
    "certifications",
]
_HEADER_RE = re.compile(
    r"^\s{0,3}#{0,3}\s*(?P<header>"
    + "|".join(re.escape(h) for h in sorted(_SECTION_HEADERS, key=len, reverse=True))
    + r")\s*:?\s*$",
    re.IGNORECASE,
)

SKILLS_TAXONOMY = [
    "product management", "product strategy", "roadmapping", "product roadmap",
    "stakeholder management", "cross-functional leadership", "agile", "scrum",
    "user research", "customer discovery", "a/b testing", "experimentation",
    "go-to-market", "gtm strategy", "prd", "product requirements",
    "okrs", "kpi", "pricing strategy", "competitive analysis",
    "p&l ownership", "fundraising", "esop", "technical product management",
    "ai product management", "llm evaluation", "rag", "retrieval augmented generation",
    "prompt engineering", "machine learning", "data analysis",
    "ux design", "wireframing", "user stories", "backlog management",
    "vendor management", "budget management", "team leadership", "hiring",
    "pharma analytics", "healthcare analytics", "market research",
]

TOOLS_TAXONOMY = [
    "python", "sql", "javascript", "typescript", "react", "node.js",
    "docker", "kubernetes", "aws", "gcp", "azure", "postgres", "mongodb",
    "git", "ci/cd", "figma", "jira", "confluence", "notion", "linear",
    "amplitude", "mixpanel", "segment", "tableau", "looker", "power bi",
    "excel", "google analytics", "salesforce", "hubspot", "zendesk",
    "langchain", "llamaindex", "pinecone", "weaviate", "openai api",
    "claude api", "anthropic api", "gemini api", "vertex ai", "bedrock",
    "hugging face", "pytorch", "tensorflow", "pandas", "numpy",
    "rest api", "graphql", "microservices", "kafka", "airflow",
]


def _find_matches(text: str, taxonomy: list[str]) -> list[str]:
    lower = text.lower()
    found = []
    for term in taxonomy:
        pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, lower):
            found.append(term)
    return found


def _split_sections(text: str) -> dict[str, str]:
    lines = text.splitlines()
    header_idx: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _HEADER_RE.match(line.strip())
        if m:
            header_idx.append((i, m.group("header").lower()))

    if not header_idx:
        return {}

    sections: dict[str, str] = {}
    for j, (start, name) in enumerate(header_idx):
        end = header_idx[j + 1][0] if j + 1 < len(header_idx) else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        # Multiple headers alias to the same logical section; keep the longest.
        canonical = {
            "work experience": "experience",
            "employment history": "experience",
            "professional experience": "experience",
            "technical skills": "skills",
            "core skills": "skills",
            "objective": "summary",
            "profile": "summary",
        }.get(name, name)
        if canonical not in sections or len(body) > len(sections[canonical]):
            sections[canonical] = body
    return sections


def _year_from_token(token: str) -> int | None:
    if token.lower() in ("present", "current", "now"):
        return datetime.now(timezone.utc).year
    m = _YEAR_RE.search(token)
    return int(m.group()) if m else None


def _parse_roles(experience_text: str) -> list[CVRole]:
    roles: list[CVRole] = []
    lines = [ln.strip() for ln in experience_text.splitlines()]
    for i, line in enumerate(lines):
        if not line:
            continue
        m = _DATE_RANGE_RE.search(line)
        if not m:
            continue

        remainder = (line[: m.start()] + line[m.end() :]).strip(" -–—|,()")
        prev_lines = [lines[k] for k in range(i - 1, -1, -1) if lines[k]][:2]

        if remainder and prev_lines and remainder.lower() != prev_lines[0].lower():
            title, company = remainder, prev_lines[0]
        elif remainder:
            title, company = remainder, None
        elif prev_lines:
            # Date range sat alone on its own line: the line right above is
            # usually the title, and the one above that the company.
            title = prev_lines[0]
            company = prev_lines[1] if len(prev_lines) > 1 else None
        else:
            title, company = "Unknown role", None

        start_year = _year_from_token(m.group("start"))
        end_year = _year_from_token(m.group("end"))
        duration = None
        if start_year and end_year and end_year >= start_year:
            duration = max(end_year - start_year, 0.5)

        # Title/company sometimes land the other way round ("Company, Title");
        # cap length so a mis-split doesn't produce a garbage multi-line field.
        roles.append(
            CVRole(
                title=title[:150],
                company=(company[:150] if company else None),
                date_range=f"{m.group('start')} - {m.group('end')}",
                duration_years=duration,
            )
        )
    return roles


def parse_cv(raw_text: str) -> CVProfile:
    raw_text = raw_text.strip()
    sections = _split_sections(raw_text)

    email_match = _EMAIL_RE.search(raw_text)
    linkedin_match = _LINKEDIN_RE.search(raw_text)
    phone_match = _PHONE_RE.search(raw_text)

    experience_text = sections.get("experience", "")
    roles = _parse_roles(experience_text) if experience_text else _parse_roles(raw_text)

    explicit_years_match = _EXPLICIT_YEARS_RE.search(raw_text)
    if explicit_years_match:
        total_years = float(explicit_years_match.group(1))
    else:
        summed = sum(r.duration_years for r in roles if r.duration_years)
        total_years = round(summed, 1) if summed else None

    skills_text = sections.get("skills", "") or raw_text
    skills = _find_matches(skills_text, SKILLS_TAXONOMY)
    tools = _find_matches(raw_text, TOOLS_TAXONOMY)

    companies = []
    for r in roles:
        if r.company and r.company not in companies:
            companies.append(r.company)

    projects_text = sections.get("projects", "")
    projects = [
        ln.strip("-*• \t")[:200]
        for ln in projects_text.splitlines()
        if ln.strip("-*• \t")
    ] if projects_text else []

    first_name_line = next((ln.strip() for ln in raw_text.splitlines() if ln.strip()), None)
    name = first_name_line[:100] if first_name_line and len(first_name_line) < 60 else None

    return CVProfile(
        raw_text=raw_text,
        name=name,
        email=email_match.group() if email_match else None,
        phone=phone_match.group().strip() if phone_match else None,
        linkedin=linkedin_match.group() if linkedin_match else None,
        total_years_experience=total_years,
        roles=roles,
        skills=skills,
        tools=tools,
        companies=companies,
        projects=projects,
        summary=sections.get("summary") or None,
        updated_at=datetime.now(timezone.utc),
    )
