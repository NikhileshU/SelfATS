import asyncio
from datetime import datetime, timezone

import pytest

from job_aggregator.application.draft import draft_application
from job_aggregator.application.submit import submit_application
from job_aggregator.cv.models import CVProfile
from job_aggregator.storage import db
from job_aggregator.storage.models import RawJob


def _seed_job(conn):
    db.upsert_raw_jobs(conn, [
        RawJob(
            id="1", title="Head of Product", company="Acme", url="https://acme.example/apply",
            source="hn", posted_at=datetime.now(timezone.utc),
            raw_description="We need product strategy and python skills",
        )
    ])
    return db.search_jobs(conn)[0].dedup_key


def test_draft_application_heuristic_fallback(tmp_path):
    db_path = tmp_path / "jobs.db"
    with db.connect(db_path) as conn:
        job_id = _seed_job(conn)
        profile = CVProfile(
            raw_text="", skills=["product strategy"], tools=["python"],
            total_years_experience=5.0, updated_at=datetime.now(timezone.utc),
        )
        draft = asyncio.run(draft_application(conn, job_id, profile, ctx=None))

        assert draft.generated_via == "heuristic"
        assert draft.company == "Acme"
        assert "Product Strategy" in draft.resume_emphasis or "Python" in draft.resume_emphasis
        assert "Head of Product" in draft.cover_note


def test_draft_application_missing_job_raises(tmp_path):
    db_path = tmp_path / "jobs.db"
    with db.connect(db_path) as conn:
        profile = CVProfile(raw_text="", updated_at=datetime.now(timezone.utc))
        with pytest.raises(ValueError):
            asyncio.run(draft_application(conn, "nonexistent", profile, ctx=None))


def test_submit_requires_confirmation(tmp_path):
    db_path = tmp_path / "jobs.db"
    with db.connect(db_path) as conn:
        job_id = _seed_job(conn)
        result = submit_application(conn, job_id, confirmed=False)
        assert result["opened"] is False
