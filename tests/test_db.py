from datetime import datetime, timezone

from job_aggregator.storage import db
from job_aggregator.storage.models import RawJob


def _raw_job(source: str, source_id: str, title="Head of Product", company="Acme Inc") -> RawJob:
    return RawJob(
        id=source_id,
        title=title,
        company=company,
        location="Remote",
        remote=True,
        url=f"https://example.com/{source}/{source_id}",
        source=source,
        posted_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        raw_description="We are hiring a product leader.",
    )


def test_dedup_across_sources(tmp_path):
    db_path = tmp_path / "jobs.db"
    with db.connect(db_path) as conn:
        stats1 = db.upsert_raw_jobs(conn, [_raw_job("hn", "1")])
        stats2 = db.upsert_raw_jobs(conn, [_raw_job("remoteok", "2")])

        assert stats1 == {"seen": 1, "new": 1}
        assert stats2 == {"seen": 1, "new": 0}  # same company+title -> collapses

        jobs = db.search_jobs(conn)
        assert len(jobs) == 1
        assert len(jobs[0].sources) == 2
        assert {s.source for s in jobs[0].sources} == {"hn", "remoteok"}


def test_search_filters(tmp_path):
    db_path = tmp_path / "jobs.db"
    with db.connect(db_path) as conn:
        db.upsert_raw_jobs(conn, [_raw_job("hn", "1", title="Head of Product", company="Acme")])
        db.upsert_raw_jobs(conn, [_raw_job("hn", "2", title="Backend Engineer", company="Beta")])

        results = db.search_jobs(conn, keyword="Head of Product")
        assert len(results) == 1
        assert results[0].company == "Acme"


def test_source_run_tracking(tmp_path):
    db_path = tmp_path / "jobs.db"
    with db.connect(db_path) as conn:
        db.record_source_run(conn, "hn", "ok", jobs_found=10, jobs_new=3)
        db.record_source_run(conn, "remoteok", "error", error="timeout")

        statuses = {s["source"]: s for s in db.list_sources_status(conn)}
        assert statuses["hn"]["status"] == "ok"
        assert statuses["remoteok"]["status"] == "error"
        assert statuses["remoteok"]["error"] == "timeout"
