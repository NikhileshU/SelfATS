"""The MCP server entrypoint. stdio transport, local-first — see
ADR-001-job-aggregator-mcp-plugin.md for the full architecture.

Every tool opens its own short-lived SQLite connection (db.connect) rather
than holding one open across the process lifetime: this is a low-QPS,
single-user tool, so the simplicity of "connect, do the work, commit,
close" outweighs any pooling benefit.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from mcp.server.fastmcp import Context, FastMCP

from job_aggregator.application import draft as draft_module
from job_aggregator.application import submit as submit_module
from job_aggregator.classify.fit_score import heuristic_score, llm_score_batch, shortlist
from job_aggregator.cv import store as cv_store
from job_aggregator.cv.parser import parse_cv
from job_aggregator.scheduler.refresh_job import refresh_all
from job_aggregator.storage import db

mcp = FastMCP(
    name="job-aggregator",
    instructions=(
        "CV-matched, multi-source job discovery. Call check_cv_status first; "
        "if no CV is on file, ask the user to paste/upload their resume text "
        "and pass it to set_cv before calling suggest_jobs. LinkedIn, "
        "Wellfound, Underdog.io, and Built In are out of scope by design — "
        "don't attempt to fetch or suggest workarounds for them."
    ),
)


def _cv_summary(profile) -> dict:
    return {
        "name": profile.name,
        "email": profile.email,
        "total_years_experience": profile.total_years_experience,
        "skills": profile.skills,
        "tools": profile.tools,
        "companies": profile.companies,
        "role_count": len(profile.roles),
        "updated_at": profile.updated_at.isoformat(),
    }


def _job_dict(job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "remote": job.remote,
        "stage": job.stage,
        "experience_signal": job.experience_signal,
        "min_years": job.min_years,
        "equity_mentioned": job.equity_mentioned,
        "salary_range": job.salary_range.model_dump(),
        "url": job.url,
        "source": job.source,
        "sources": [s.model_dump(mode="json") for s in job.sources],
        "posted_at": job.posted_at.isoformat() if hasattr(job.posted_at, "isoformat") else job.posted_at,
        "fit_score": job.fit_score,
        "fit_rationale": job.fit_rationale,
    }


@mcp.tool()
def check_cv_status() -> dict:
    """Check whether a CV is on file. Call this before suggest_jobs or
    draft_application — both need a parsed CV profile to work."""
    if not cv_store.has_profile():
        return {"has_cv": False, "message": "No CV on file. Ask the user to paste their resume text, then call set_cv."}
    profile = cv_store.load_profile()
    return {"has_cv": True, "summary": _cv_summary(profile)}


@mcp.tool()
def set_cv(content: str) -> dict:
    """Parse raw CV/resume text and persist it as the candidate profile used
    for job matching. Call this once the user has provided their CV text."""
    profile = parse_cv(content)
    cv_store.save_profile(profile)
    return {"saved": True, "summary": _cv_summary(profile)}


@mcp.tool()
def update_cv(content: str) -> dict:
    """Replace the stored CV with new resume text (e.g. after the user
    updates their resume). Same behavior as set_cv."""
    profile = parse_cv(content)
    cv_store.save_profile(profile)
    return {"saved": True, "summary": _cv_summary(profile)}


@mcp.tool()
def search_jobs(
    stage: Optional[str] = None,
    remote: Optional[bool] = None,
    experience_signal: Optional[str] = None,
    min_fit_score: Optional[float] = None,
    keyword: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Search the cached job listings with filters. stage is one of
    early-stage/pre-seed/seed/small/mid/large/mnc/unknown. experience_signal
    is one of explicit_years/skills_first/unclear. source matches an
    adapter name (hn, remoteok, remotive, wwr, greenhouse, lever, ashby)."""
    with db.connect() as conn:
        jobs = db.search_jobs(
            conn, stage=stage, remote=remote, experience_signal=experience_signal,
            min_fit_score=min_fit_score, keyword=keyword, source=source, limit=limit,
        )
        return {"count": len(jobs), "jobs": [_job_dict(j) for j in jobs]}


@mcp.tool()
async def suggest_jobs(top_n: int = 10, ctx: Context = None) -> dict:
    """Rank cached jobs against the stored CV and return the best matches,
    split by whether they hard-gate on years of experience. Requires a CV —
    check check_cv_status/set_cv first. Scores and persists fit_score for
    every job it evaluates, so a later search_jobs(min_fit_score=...) can
    reuse the ranking without recomputing it."""
    if not cv_store.has_profile():
        return {"cv_required": True, "message": "No CV on file. Ask the user for their resume text, then call set_cv."}
    profile = cv_store.load_profile()

    with db.connect() as conn:
        candidates = db.search_jobs(conn, limit=500)
        if not candidates:
            return {"cv_required": False, "results": [], "message": "Job cache is empty — call refresh_cache first."}

        pool = shortlist(candidates, profile, top_n)
        llm_scores = await llm_score_batch(ctx, profile, pool) if ctx is not None else {}

        scored = []
        for job in pool:
            if job.id in llm_scores:
                score, rationale, exp_signal_override = llm_scores[job.id]
                if exp_signal_override in ("explicit_years", "skills_first", "unclear"):
                    db.update_classification(conn, job.dedup_key, experience_signal=exp_signal_override)
                    job.experience_signal = exp_signal_override
            else:
                score, rationale = heuristic_score(job, profile), ""
            db.set_fit_score(conn, job.dedup_key, score, rationale)
            job.fit_score = score
            job.fit_rationale = rationale
            scored.append(job)

        scored.sort(key=lambda j: j.fit_score or 0.0, reverse=True)
        top = scored[:top_n]

        gated: dict[str, list[str]] = {"explicit_years": [], "skills_first": [], "unclear": []}
        for j in top:
            gated[j.experience_signal].append(j.id)

        return {
            "cv_required": False,
            "scored_via": "llm" if llm_scores else "heuristic",
            "results": [_job_dict(j) for j in top],
            "by_experience_gate": gated,
        }


@mcp.tool()
def get_job_details(id: str) -> dict:
    """Fetch the full cached record for one job by its id (the dedup_key
    returned from search_jobs/suggest_jobs)."""
    with db.connect() as conn:
        job = db.get_job(conn, id)
        if job is None:
            return {"found": False, "message": f"no job found for id {id!r}"}
        return {"found": True, "job": _job_dict(job)}


@mcp.tool()
def list_sources_status() -> dict:
    """Per-source refresh health: last run time, status, error (if any),
    and job counts. One broken source never hides the others being fine."""
    with db.connect() as conn:
        return {"sources": db.list_sources_status(conn)}


@mcp.tool()
def refresh_cache(source: Optional[str] = None) -> dict:
    """Fetch fresh listings from all sources (or just one, if `source` is
    given) and re-run classification. This hits live source APIs directly —
    no GitHub Actions or network setup required, it always works standalone.
    Can take a while with all sources; pass a single source name to test
    one adapter quickly."""
    sources = [source] if source else None
    return refresh_all(sources=sources)


@mcp.tool()
async def draft_application(job_id: str, ctx: Context = None) -> dict:
    """Generate a tailored resume-emphasis list and cover note for a
    specific job, for the user to review. Requires a CV on file. Does not
    submit anything — see submit_application."""
    if not cv_store.has_profile():
        return {"cv_required": True, "message": "No CV on file. Ask the user for their resume text, then call set_cv."}
    profile = cv_store.load_profile()

    with db.connect() as conn:
        try:
            draft = await draft_module.draft_application(conn, job_id, profile, ctx)
        except ValueError as exc:
            return {"found": False, "message": str(exc)}
        return {"found": True, "draft": draft.model_dump()}


@mcp.tool()
def submit_application(job_id: str, confirmed: bool = False) -> dict:
    """Open the job's real application page in the browser — only after the
    user has reviewed draft_application's output and explicitly confirmed.
    No ATS exposes a public submit API usable without the hiring company's
    own credentials, so this never auto-fills or auto-submits a form; it
    just takes you to the real listing to finish applying yourself."""
    with db.connect() as conn:
        try:
            return submit_module.submit_application(conn, job_id, confirmed)
        except ValueError as exc:
            return {"opened": False, "message": str(exc)}


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
