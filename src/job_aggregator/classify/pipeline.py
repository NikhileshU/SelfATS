"""Orchestrates the heuristic classification pass over jobs the cache hasn't
scored yet. The LLM-assisted fit-score pass (classify/fit_score.py) runs
separately, on-demand, from the suggest_jobs tool — it needs a live MCP
Context to sample through, which this module doesn't have."""
from __future__ import annotations

import sqlite3

from job_aggregator.classify import experience_gate, stage_size
from job_aggregator.storage import db


def run_heuristic_classification(conn: sqlite3.Connection, limit: int = 2000) -> int:
    jobs = db.jobs_missing_classification(conn, limit=limit)
    for job in jobs:
        yc = db.get_yc_company_by_name(conn, job.company)
        stage = stage_size.classify_stage(
            job.company, job.raw_description, yc_stage=yc["stage"] if yc else None
        )
        exp_signal, min_years = experience_gate.classify_experience(job.raw_description)
        db.update_classification(
            conn, job.dedup_key, stage=stage, experience_signal=exp_signal, min_years=min_years
        )
    return len(jobs)
