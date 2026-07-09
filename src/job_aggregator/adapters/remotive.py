"""Remotive — public API (https://remotive.com/api/remote-jobs). Every
listing is remote by definition. Salary is freeform text on this board
("$50-$75 /hour", "$120k-$150k", etc) — too inconsistent to parse reliably
into salary_range, so it's left null and folded into raw_description
instead of risking silently wrong structured numbers."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from job_aggregator.adapters.base import AdapterError, equity_mentioned, get_client, strip_html
from job_aggregator.storage.models import RawJob

SOURCE = "remotive"
API_URL = "https://remotive.com/api/remote-jobs"


def fetch() -> list[RawJob]:
    try:
        with get_client() as client:
            resp = client.get(API_URL)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise AdapterError(f"remotive: {exc}") from exc

    jobs = []
    for item in data.get("jobs", []):
        description = strip_html(item.get("description") or "")
        salary_text = item.get("salary") or ""
        if salary_text:
            description = f"Salary: {salary_text}\n\n{description}"

        posted_raw = item.get("publication_date")
        posted_at = (
            datetime.fromisoformat(posted_raw).replace(tzinfo=timezone.utc)
            if posted_raw
            else datetime.now(timezone.utc)
        )

        jobs.append(
            RawJob(
                id=str(item["id"]),
                title=item.get("title", "")[:200] or "Untitled role",
                company=item.get("company_name", "")[:200] or "Unknown",
                location=item.get("candidate_required_location") or None,
                remote=True,
                url=item.get("url") or "",
                source=SOURCE,
                posted_at=posted_at,
                raw_description=description[:6000],
                equity_mentioned=equity_mentioned(description),
            )
        )
    return jobs
