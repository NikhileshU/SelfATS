from datetime import datetime, timezone

from job_aggregator.classify import experience_gate, stage_size
from job_aggregator.classify.fit_score import heuristic_score
from job_aggregator.classify.pipeline import run_heuristic_classification
from job_aggregator.cv.models import CVProfile
from job_aggregator.storage import db
from job_aggregator.storage.models import RawJob


def test_classify_stage_mnc():
    assert stage_size.classify_stage("Google", "") == "mnc"
    assert stage_size.classify_stage("Tata Consultancy Services", "") == "mnc"


def test_classify_stage_from_phrases():
    assert stage_size.classify_stage("Acme", "We are a seed-funded startup") == "seed"
    assert stage_size.classify_stage("Acme", "Backed by Y Combinator, Series A") == "early-stage"
    assert stage_size.classify_stage("Acme", "no funding signal here") == "unknown"


def test_classify_stage_yc_override():
    assert stage_size.classify_stage("Acme", "Series C growth stage", yc_stage="early-stage") == "early-stage"


def test_experience_gate_explicit_years():
    signal, years = experience_gate.classify_experience("Looking for 5+ years of experience in product")
    assert signal == "explicit_years"
    assert years == 5


def test_experience_gate_skills_first():
    signal, years = experience_gate.classify_experience("No degree required, we care about what you can do")
    assert signal == "skills_first"
    assert years is None


def test_experience_gate_unclear():
    signal, years = experience_gate.classify_experience("Join our growing team")
    assert signal == "unclear"
    assert years is None


def test_heuristic_score_rewards_title_and_skill_match():
    profile = CVProfile(
        raw_text="", skills=["product strategy"], tools=["python"],
        updated_at=datetime.now(timezone.utc),
    )
    good_job = RawJob(
        id="1", title="Head of Product", company="Acme", url="https://x",
        source="hn", posted_at=datetime.now(timezone.utc),
        raw_description="We need product strategy and python skills",
    )
    from job_aggregator.storage.models import Job, dedup_key_for
    good = Job(**good_job.model_dump(), dedup_key=dedup_key_for("Acme", "Head of Product"),
               first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc))

    bad_raw = RawJob(
        id="2", title="Warehouse Associate", company="Acme", url="https://x",
        source="hn", posted_at=datetime.now(timezone.utc), raw_description="lift boxes",
    )
    bad = Job(**bad_raw.model_dump(), dedup_key=dedup_key_for("Acme", "Warehouse Associate"),
              first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc))

    assert heuristic_score(good, profile) > heuristic_score(bad, profile)


def test_run_heuristic_classification_updates_jobs(tmp_path):
    db_path = tmp_path / "jobs.db"
    with db.connect(db_path) as conn:
        db.upsert_raw_jobs(conn, [
            RawJob(
                id="1", title="Head of Product", company="Google", url="https://x",
                source="hn", posted_at=datetime.now(timezone.utc),
                raw_description="5+ years of experience required",
            )
        ])
        updated = run_heuristic_classification(conn)
        assert updated == 1

        jobs = db.search_jobs(conn)
        assert jobs[0].stage == "mnc"
        assert jobs[0].experience_signal == "explicit_years"
        assert jobs[0].min_years == 5
