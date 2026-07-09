"""Generates a tailored resume-emphasis + cover note for a specific job,
for the user to review before deciding whether to apply.

Uses the same MCP-sampling pattern as classify/fit_score.py: an LLM-assisted
draft when the connected client supports sampling, falling back to a
template built from skill/tool overlap when it doesn't. Either way this
never submits anything — see application/submit.py for why there's no
programmatic submission path at all.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Optional

from mcp import types
from mcp.server.fastmcp import Context

from job_aggregator.application.models import ApplicationDraft
from job_aggregator.cv.models import CVProfile
from job_aggregator.storage import db

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _heuristic_draft(profile: CVProfile, job: db.Job) -> tuple[list[str], str]:
    job_text = f"{job.title} {job.raw_description}".lower()
    matched_skills = [s for s in profile.skills if s in job_text]
    matched_tools = [t for t in profile.tools if t in job_text]
    emphasis = [s.title() for s in (matched_skills + matched_tools)[:6]] or [
        "Product management experience relevant to this role"
    ]

    years = f"{profile.total_years_experience:g} years" if profile.total_years_experience else "several years"
    cover_note = (
        f"I'm interested in the {job.title} role at {job.company}. "
        f"I bring {years} of experience across product and engineering, "
        f"including hands-on work with {', '.join(emphasis[:3]).lower() or 'related tools'}. "
        f"I'd welcome the chance to discuss how that background applies here."
    )
    return emphasis, cover_note


def _build_prompt(profile: CVProfile, job: db.Job) -> str:
    return (
        "Candidate background:\n"
        f"Years of experience: {profile.total_years_experience or 'unknown'}\n"
        f"Skills: {', '.join(profile.skills) or 'none extracted'}\n"
        f"Tools: {', '.join(profile.tools) or 'none extracted'}\n"
        f"Recent companies: {', '.join(profile.companies) or 'none extracted'}\n"
        f"Summary: {profile.summary or '(none)'}\n\n"
        f"Job: {job.title} at {job.company}\n"
        f"Description: {(job.raw_description or '')[:2000]}\n\n"
        "Write application materials for this candidate applying to this "
        "job. Respond with ONLY JSON, no prose, no markdown fences:\n"
        '{"resume_emphasis": ["short phrase", "..."], "cover_note": "2-4 sentence note"}'
    )


async def _llm_draft(ctx: Context, profile: CVProfile, job: db.Job) -> Optional[tuple[list[str], str]]:
    try:
        response = await ctx.session.create_message(
            messages=[
                types.SamplingMessage(
                    role="user", content=types.TextContent(type="text", text=_build_prompt(profile, job))
                )
            ],
            max_tokens=800,
            system_prompt="You write tailored job application materials. Respond with strict JSON only.",
        )
    except Exception:
        return None

    if not isinstance(response.content, types.TextContent):
        return None

    text = response.content.text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    emphasis = parsed.get("resume_emphasis")
    cover_note = parsed.get("cover_note")
    if not emphasis or not cover_note:
        return None
    return list(emphasis), str(cover_note)


async def draft_application(
    conn: sqlite3.Connection, job_id: str, profile: CVProfile, ctx: Optional[Context] = None
) -> ApplicationDraft:
    job = db.get_job(conn, job_id)
    if job is None:
        raise ValueError(f"no job found for id {job_id!r}")

    llm_result = await _llm_draft(ctx, profile, job) if ctx is not None else None
    if llm_result:
        emphasis, cover_note = llm_result
        via = "llm"
    else:
        emphasis, cover_note = _heuristic_draft(profile, job)
        via = "heuristic"

    return ApplicationDraft(
        job_id=job.id,
        job_title=job.title,
        company=job.company,
        url=job.url,
        resume_emphasis=emphasis,
        cover_note=cover_note,
        generated_via=via,
    )
