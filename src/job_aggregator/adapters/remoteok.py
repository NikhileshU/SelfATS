"""RemoteOK — public JSON API (https://remoteok.com/api). Every listing on
this board is remote by definition, so remote is always True."""
from __future__ import annotations

from datetime import datetime

import httpx

from job_aggregator.adapters.base import AdapterError, equity_mentioned, get_client, strip_html
from job_aggregator.storage.models import RawJob

SOURCE = "remoteok"
API_URL = "https://remoteok.com/api"


def fetch() -> list[RawJob]:
    try:
        with get_client() as client:
            resp = client.get(API_URL)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise AdapterError(f"remoteok: {exc}") from exc

    jobs = []
    for item in data:
        if "id" not in item:  # first element is a legal/metadata banner, not a job
            continue
        description = strip_html(item.get("description") or "")
        salary_min = item.get("salary_min") or None
        salary_max = item.get("salary_max") or None
        jobs.append(
            RawJob(
                id=str(item["id"]),
                title=item.get("position", "")[:200] or "Untitled role",
                company=item.get("company", "")[:200] or "Unknown",
                location=item.get("location") or None,
                remote=True,
                salary_range={"min": salary_min, "max": salary_max, "currency": "USD" if salary_min else None},
                url=item.get("url") or item.get("apply_url") or "",
                source=SOURCE,
                posted_at=datetime.fromisoformat(item["date"]),
                raw_description=description[:6000],
                equity_mentioned=equity_mentioned(description),
            )
        )
    return jobs
