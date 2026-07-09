"""yc-oss/api (github.com/yc-oss/api) — YC's company directory, mirrored via
Algolia and updated daily by that repo's own GitHub Actions.

Verified at build time: this endpoint returns company records (stage, team
size, isHiring flag) — it does NOT expose individual job postings (no
per-role title/description). Forcing "isHiring" companies into the jobs
table as fake listings would produce entries with no real role to apply to.

So this adapter deviates from a literal RawJob-emitting source: it instead
populates the yc_companies enrichment table, which classify/stage_size.py
consults to get an authoritative stage for any job whose company matches a
YC company by name. That's the accurate use of this data.
"""
from __future__ import annotations

import httpx

from job_aggregator.adapters.base import AdapterError, get_client
from job_aggregator.storage import db

SOURCE = "yc"
COMPANIES_URL = "https://yc-oss.github.io/api/companies/all.json"

# yc-oss stage strings -> this project's stage buckets.
_STAGE_MAP = {
    "early": "early-stage",
    "growth": "mid",
    "late": "large",
}


def _map_stage(yc_stage: str | None) -> str | None:
    if not yc_stage:
        return None
    return _STAGE_MAP.get(yc_stage.strip().lower())


def fetch_companies() -> list[dict]:
    try:
        with get_client(timeout=30.0) as client:
            resp = client.get(COMPANIES_URL)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise AdapterError(f"yc_oss: {exc}") from exc

    companies = []
    for c in data:
        companies.append(
            {
                "slug": c["slug"],
                "name": c["name"],
                "stage": _map_stage(c.get("stage")),
                "team_size": c.get("team_size"),
                "batch": c.get("batch"),
                "is_hiring": bool(c.get("isHiring")),
                "regions": ", ".join(c.get("regions") or []) or None,
                "website": c.get("website"),
            }
        )
    return companies


def refresh(conn) -> int:
    """Populate/update the yc_companies enrichment table. Not a job-listing
    fetch — see module docstring."""
    companies = fetch_companies()
    return db.upsert_yc_companies(conn, companies)
