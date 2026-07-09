"""Greenhouse — semi-public JSON board endpoints, one company per API call.
A single company's board failing (wrong slug, board taken down) must not
drop every other company's listings, so failures are logged and skipped
per-company rather than raising out of fetch()."""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from job_aggregator.adapters.base import equity_mentioned, get_client, strip_html
from job_aggregator.adapters.company_boards import load_slugs
from job_aggregator.storage.models import RawJob

SOURCE_PREFIX = "greenhouse"
BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"

logger = logging.getLogger(__name__)


def _fetch_company(client: httpx.Client, company: str) -> list[RawJob]:
    resp = client.get(BOARD_URL.format(company=company))
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for item in data.get("jobs", []):
        description = strip_html(item.get("content") or "")
        location = (item.get("location") or {}).get("name")
        jobs.append(
            RawJob(
                id=str(item["id"]),
                title=item.get("title", "")[:200] or "Untitled role",
                company=item.get("company_name") or company,
                location=location,
                remote=bool(location and "remote" in location.lower()),
                url=item.get("absolute_url", ""),
                source=f"{SOURCE_PREFIX}:{company}",
                posted_at=datetime.fromisoformat(item["first_published"]),
                raw_description=description[:6000],
                equity_mentioned=equity_mentioned(description),
            )
        )
    return jobs


def fetch() -> list[RawJob]:
    jobs: list[RawJob] = []
    with get_client() as client:
        for company in load_slugs("greenhouse"):
            try:
                jobs.extend(_fetch_company(client, company))
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                logger.warning("greenhouse:%s failed: %s", company, exc)
    return jobs
