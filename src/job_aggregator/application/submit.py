"""No source actually exposes a public "submit application" API a
third-party tool can call: Greenhouse and Lever both gate their submission
endpoints behind the *hiring company's* private API key, and Ashby's public
apply flow is an undocumented internal SPA endpoint — automating it would
be the same ToS grey zone ADR-001 explicitly ruled out for LinkedIn.

So "submit" here means what's actually safe and real: open the listing's
real application page in the user's browser, only after they've reviewed
the draft (application/draft.py) and explicitly confirmed. No form is
auto-filled and nothing is auto-submitted.
"""
from __future__ import annotations

import sqlite3
import webbrowser

from job_aggregator.storage import db


def submit_application(conn: sqlite3.Connection, job_id: str, confirmed: bool) -> dict:
    job = db.get_job(conn, job_id)
    if job is None:
        raise ValueError(f"no job found for id {job_id!r}")

    if not confirmed:
        return {
            "opened": False,
            "reason": "confirmed=false — call draft_application first, review it with the user, "
            "then call submit_application again with confirmed=true only after they agree.",
            "url": job.url,
        }

    webbrowser.open(job.url)
    return {
        "opened": True,
        "url": job.url,
        "note": "Opened the listing's real application page in your browser. "
        "No form was filled in or submitted automatically — finish the application there.",
    }
