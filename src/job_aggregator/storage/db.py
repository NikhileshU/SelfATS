"""SQLite-backed job cache: schema, upsert/dedup, and query helpers.

Two tables:
  jobs         — one canonical, deduped row per (company, title) pair.
  job_sources  — every place a canonical job was seen (one row per source
                 posting), so re-postings across boards collapse into a
                 single job while still tracking every source URL.

A third table, source_runs, tracks per-adapter refresh health so one broken
source doesn't hide the fact that every other source is fine.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

from job_aggregator.storage.models import Job, JobSource, RawJob, SalaryRange, dedup_key_for

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "jobs.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    dedup_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    remote INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT 'unknown',
    experience_signal TEXT NOT NULL DEFAULT 'unclear',
    min_years INTEGER,
    equity_mentioned INTEGER NOT NULL DEFAULT 0,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency TEXT,
    raw_description TEXT NOT NULL DEFAULT '',
    fit_score REAL,
    fit_rationale TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_sources (
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    dedup_key TEXT NOT NULL REFERENCES jobs(dedup_key) ON DELETE CASCADE,
    url TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_job_sources_dedup ON job_sources(dedup_key);

CREATE TABLE IF NOT EXISTS source_runs (
    source TEXT PRIMARY KEY,
    last_run_at TEXT,
    status TEXT,
    error TEXT,
    jobs_found INTEGER DEFAULT 0,
    jobs_new INTEGER DEFAULT 0
);

-- yc-oss/api serves the YC company directory (stage, team size, isHiring),
-- not individual job postings — no title/description per opening exists.
-- Kept separate from `jobs` and used as an enrichment lookup by
-- classify/stage_size.py rather than forced into the job schema.
CREATE TABLE IF NOT EXISTS yc_companies (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    stage TEXT,
    team_size INTEGER,
    batch TEXT,
    is_hiring INTEGER NOT NULL DEFAULT 0,
    regions TEXT,
    website TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_yc_companies_name_norm ON yc_companies(name_normalized);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(db_path: Path | str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_raw_jobs(conn: sqlite3.Connection, raw_jobs: Iterable[RawJob]) -> dict:
    """Insert/merge a batch of adapter output. Returns {"seen": n, "new": n}."""
    seen = 0
    new = 0
    now = _now()
    for job in raw_jobs:
        seen += 1
        dedup_key = dedup_key_for(job.company, job.title)
        row = conn.execute(
            "SELECT 1 FROM jobs WHERE dedup_key = ?", (dedup_key,)
        ).fetchone()

        if row is None:
            new += 1
            conn.execute(
                """INSERT INTO jobs (
                    dedup_key, title, company, location, remote, stage,
                    experience_signal, min_years, equity_mentioned,
                    salary_min, salary_max, salary_currency, raw_description,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    dedup_key, job.title, job.company, job.location,
                    int(job.remote), job.stage, job.experience_signal,
                    job.min_years, int(job.equity_mentioned),
                    job.salary_range.min, job.salary_range.max,
                    job.salary_range.currency, job.raw_description,
                    now, now,
                ),
            )
        else:
            # Fill in fields opportunistically: only overwrite "unknown"/blank
            # values, never clobber a more specific classification with a
            # weaker one from a later-seen duplicate posting.
            conn.execute(
                """UPDATE jobs SET
                    last_seen_at = ?,
                    location = COALESCE(location, ?),
                    stage = CASE WHEN stage = 'unknown' THEN ? ELSE stage END,
                    experience_signal = CASE WHEN experience_signal = 'unclear'
                        THEN ? ELSE experience_signal END,
                    min_years = COALESCE(min_years, ?),
                    salary_min = COALESCE(salary_min, ?),
                    salary_max = COALESCE(salary_max, ?),
                    salary_currency = COALESCE(salary_currency, ?),
                    equity_mentioned = MAX(equity_mentioned, ?),
                    raw_description = CASE WHEN length(raw_description) < ?
                        THEN ? ELSE raw_description END
                WHERE dedup_key = ?""",
                (
                    now, job.location, job.stage, job.experience_signal,
                    job.min_years, job.salary_range.min, job.salary_range.max,
                    job.salary_range.currency, int(job.equity_mentioned),
                    len(job.raw_description), job.raw_description,
                    dedup_key,
                ),
            )

        cur = conn.execute(
            """INSERT INTO job_sources (source, source_id, dedup_key, url, posted_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(source, source_id) DO UPDATE SET
                   dedup_key = excluded.dedup_key,
                   url = excluded.url,
                   posted_at = excluded.posted_at""",
            (job.source, job.id, dedup_key, job.url, job.posted_at.isoformat()),
        )
        del cur

    return {"seen": seen, "new": new}


def record_source_run(
    conn: sqlite3.Connection,
    source: str,
    status: str,
    error: Optional[str] = None,
    jobs_found: int = 0,
    jobs_new: int = 0,
) -> None:
    conn.execute(
        """INSERT INTO source_runs (source, last_run_at, status, error, jobs_found, jobs_new)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(source) DO UPDATE SET
               last_run_at = excluded.last_run_at,
               status = excluded.status,
               error = excluded.error,
               jobs_found = excluded.jobs_found,
               jobs_new = excluded.jobs_new""",
        (source, _now(), status, error, jobs_found, jobs_new),
    )


def list_sources_status(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM source_runs ORDER BY source"
    ).fetchall()
    return [dict(r) for r in rows]


def _row_to_job(conn: sqlite3.Connection, row: sqlite3.Row) -> Job:
    src_rows = conn.execute(
        "SELECT source, source_id, url, posted_at FROM job_sources WHERE dedup_key = ? ORDER BY posted_at ASC",
        (row["dedup_key"],),
    ).fetchall()
    sources = [
        JobSource(source=r["source"], source_id=r["source_id"], url=r["url"], posted_at=r["posted_at"])
        for r in src_rows
    ]
    earliest = sources[0] if sources else None
    return Job(
        id=row["dedup_key"],
        dedup_key=row["dedup_key"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        remote=bool(row["remote"]),
        stage=row["stage"],
        experience_signal=row["experience_signal"],
        min_years=row["min_years"],
        equity_mentioned=bool(row["equity_mentioned"]),
        salary_range=SalaryRange(
            min=row["salary_min"], max=row["salary_max"], currency=row["salary_currency"]
        ),
        url=earliest.url if earliest else "",
        source=earliest.source if earliest else "",
        posted_at=earliest.posted_at if earliest else row["first_seen_at"],
        raw_description=row["raw_description"] or "",
        sources=sources,
        fit_score=row["fit_score"],
        fit_rationale=row["fit_rationale"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
    )


def get_job(conn: sqlite3.Connection, dedup_key: str) -> Optional[Job]:
    row = conn.execute("SELECT * FROM jobs WHERE dedup_key = ?", (dedup_key,)).fetchone()
    return _row_to_job(conn, row) if row else None


def search_jobs(
    conn: sqlite3.Connection,
    *,
    stage: Optional[str] = None,
    remote: Optional[bool] = None,
    experience_signal: Optional[str] = None,
    min_fit_score: Optional[float] = None,
    keyword: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Job]:
    clauses = []
    params: list = []

    if stage:
        clauses.append("j.stage = ?")
        params.append(stage)
    if remote is not None:
        clauses.append("j.remote = ?")
        params.append(int(remote))
    if experience_signal:
        clauses.append("j.experience_signal = ?")
        params.append(experience_signal)
    if min_fit_score is not None:
        clauses.append("j.fit_score IS NOT NULL AND j.fit_score >= ?")
        params.append(min_fit_score)
    if keyword:
        clauses.append("(j.title LIKE ? OR j.company LIKE ? OR j.raw_description LIKE ?)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    if source:
        clauses.append(
            "j.dedup_key IN (SELECT dedup_key FROM job_sources WHERE source = ?)"
        )
        params.append(source)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT j.* FROM jobs j
        {where}
        ORDER BY j.last_seen_at DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    return [_row_to_job(conn, r) for r in rows]


def set_fit_score(conn: sqlite3.Connection, dedup_key: str, score: float, rationale: str) -> None:
    conn.execute(
        "UPDATE jobs SET fit_score = ?, fit_rationale = ? WHERE dedup_key = ?",
        (score, rationale, dedup_key),
    )


def update_classification(
    conn: sqlite3.Connection,
    dedup_key: str,
    *,
    stage: Optional[str] = None,
    experience_signal: Optional[str] = None,
    min_years: Optional[int] = None,
) -> None:
    """Written by classify/*.py after scoring a job already in the cache."""
    sets = []
    params: list = []
    if stage is not None:
        sets.append("stage = ?")
        params.append(stage)
    if experience_signal is not None:
        sets.append("experience_signal = ?")
        params.append(experience_signal)
    if min_years is not None:
        sets.append("min_years = ?")
        params.append(min_years)
    if not sets:
        return
    params.append(dedup_key)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE dedup_key = ?", params)


def jobs_missing_classification(conn: sqlite3.Connection, limit: int = 500) -> list[Job]:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE stage = 'unknown' OR experience_signal = 'unclear' LIMIT ?",
        (limit,),
    ).fetchall()
    return [_row_to_job(conn, r) for r in rows]


def upsert_yc_companies(conn: sqlite3.Connection, companies: Iterable[dict]) -> int:
    from job_aggregator.storage.models import normalize_text

    now = _now()
    count = 0
    for c in companies:
        count += 1
        conn.execute(
            """INSERT INTO yc_companies (
                slug, name, name_normalized, stage, team_size, batch,
                is_hiring, regions, website, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                name_normalized = excluded.name_normalized,
                stage = excluded.stage,
                team_size = excluded.team_size,
                batch = excluded.batch,
                is_hiring = excluded.is_hiring,
                regions = excluded.regions,
                website = excluded.website,
                updated_at = excluded.updated_at""",
            (
                c["slug"], c["name"], normalize_text(c["name"]), c.get("stage"),
                c.get("team_size"), c.get("batch"), int(c.get("is_hiring", False)),
                c.get("regions"), c.get("website"), now,
            ),
        )
    return count


def get_yc_company_by_name(conn: sqlite3.Connection, company_name: str) -> Optional[dict]:
    from job_aggregator.storage.models import normalize_text

    row = conn.execute(
        "SELECT * FROM yc_companies WHERE name_normalized = ?",
        (normalize_text(company_name),),
    ).fetchone()
    return dict(row) if row else None
