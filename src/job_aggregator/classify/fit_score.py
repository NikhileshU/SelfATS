"""Hybrid fit scoring per ADR-001: a cheap heuristic pass shrinks the full
cache down to a shortlist, then an LLM-assisted pass judges that shortlist
for real nuance (e.g. "AI PM" ~= "Technical PM"). The LLM call goes through
MCP sampling (ctx.session.create_message) — since this server only ever
runs inside a Claude client, there's no need for a separate Anthropic API
key. If the connected client doesn't support sampling, callers just get the
heuristic-only scores back; nothing breaks.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from mcp import types
from mcp.server.fastmcp import Context

from job_aggregator.cv.models import CVProfile
from job_aggregator.storage.models import Job

TITLE_KEYWORDS = [
    "head of product", "technical product manager", "technical pm",
    "ai product manager", "ai pm", "product manager", "product lead",
    "director of product", "vp of product", "vp product",
    "group product manager", "principal product manager",
    "senior product manager", "fractional cpo", "chief product officer", "cpo",
]


def heuristic_score(job: Job, profile: CVProfile) -> float:
    """0-1 first-pass score: title keyword match + skill/tool overlap.
    Cheap and instant — good enough to rank the full cache down to a
    shortlist before spending an LLM call on anything."""
    score = 0.0
    title_lower = job.title.lower()
    if any(k in title_lower for k in TITLE_KEYWORDS):
        score += 0.4

    job_text = f"{job.title} {job.raw_description}".lower()
    skill_hits = sum(1 for s in profile.skills if s in job_text)
    tool_hits = sum(1 for t in profile.tools if t in job_text)
    score += min(skill_hits * 0.05, 0.3)
    score += min(tool_hits * 0.03, 0.2)

    if job.experience_signal == "skills_first":
        score += 0.1

    return min(score, 1.0)


def shortlist(jobs: list[Job], profile: CVProfile, top_n: int) -> list[Job]:
    scored = sorted(jobs, key=lambda j: heuristic_score(j, profile), reverse=True)
    # Widen past top_n so the LLM pass has real signal to differentiate,
    # not just the heuristic's own ranking restated.
    return scored[: max(top_n * 3, 20)]


_JSON_BLOCK_RE = re.compile(r"\[.*\]", re.DOTALL)


def _build_prompt(profile: CVProfile, jobs: list[Job]) -> str:
    profile_summary = (
        f"Years of experience: {profile.total_years_experience or 'unknown'}\n"
        f"Skills: {', '.join(profile.skills) or 'none extracted'}\n"
        f"Tools: {', '.join(profile.tools) or 'none extracted'}\n"
        f"Companies: {', '.join(profile.companies) or 'none extracted'}\n"
        f"Summary: {profile.summary or '(none)'}\n"
    )
    listings = []
    for j in jobs:
        desc = (j.raw_description or "")[:1200]
        listings.append(
            f'id: "{j.id}"\ntitle: {j.title}\ncompany: {j.company}\n'
            f"stage: {j.stage}\nexperience_signal: {j.experience_signal}\n"
            f"description: {desc}"
        )
    listings_block = "\n---\n".join(listings)

    return (
        "Candidate profile:\n"
        f"{profile_summary}\n"
        "Score how well each job listing below fits this candidate, on the "
        "candidate's stated target of Head of Product / Technical PM / AI PM "
        "roles. Consider skill/title equivalence (e.g. 'AI PM' and "
        "'Technical PM' are close matches for this profile), not just exact "
        "keyword overlap. Also re-judge experience_signal if the heuristic "
        "got it wrong: 'explicit_years' (hard-gated on years), 'skills_first' "
        "(work/portfolio judged, no hard year gate), or 'unclear'.\n\n"
        "Respond with ONLY a JSON array, no prose, no markdown fences:\n"
        '[{"id": "...", "score": 0.0-1.0, "rationale": "one sentence", '
        '"experience_signal": "explicit_years|skills_first|unclear"}]\n\n'
        f"Listings:\n{listings_block}"
    )


def _parse_llm_response(text: str) -> list[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []


async def llm_score_batch(
    ctx: Context, profile: CVProfile, jobs: list[Job], batch_size: int = 8
) -> dict[str, tuple[float, str, Optional[str]]]:
    """Returns {job_id: (score, rationale, experience_signal_or_None)}.
    Empty dict if sampling isn't supported by the connected client — callers
    should treat that as "fall back to heuristic scores", not an error."""
    results: dict[str, tuple[float, str, Optional[str]]] = {}

    for i in range(0, len(jobs), batch_size):
        batch = jobs[i : i + batch_size]
        prompt = _build_prompt(profile, batch)
        try:
            response = await ctx.session.create_message(
                messages=[
                    types.SamplingMessage(
                        role="user",
                        content=types.TextContent(type="text", text=prompt),
                    )
                ],
                max_tokens=2000,
                system_prompt=(
                    "You score job listings for candidate fit. "
                    "Respond with strict JSON only, no other text."
                ),
            )
        except Exception:
            return {}

        if not isinstance(response.content, types.TextContent):
            continue
        for entry in _parse_llm_response(response.content.text):
            job_id = entry.get("id")
            if not job_id:
                continue
            score = float(entry.get("score", 0.0))
            rationale = str(entry.get("rationale", ""))[:500]
            exp_signal = entry.get("experience_signal")
            results[job_id] = (max(0.0, min(1.0, score)), rationale, exp_signal)

    return results
