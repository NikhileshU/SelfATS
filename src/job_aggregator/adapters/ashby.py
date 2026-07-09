"""Ashby — public job-board API, one company per API call."""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from job_aggregator.adapters.base import equity_mentioned, get_client, strip_html
from job_aggregator.adapters.company_boards import load_slugs
from job_aggregator.storage.models import RawJob

SOURCE_PREFIX = "ashby"
BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{company}"

logger = logging.getLogger(__name__)


def _fetch_company(client: httpx.Client, company: str) -> list[RawJob]:
    resp = client.get(BOARD_URL.format(company=company))
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for item in data.get("jobs", []):
        description = strip_html(item.get("descriptionHtml") or "")
        jobs.append(
            RawJob(
                id=str(item["id"]),
                title=item.get("title", "")[:200] or "Untitled role",
                company=company,
                location=item.get("location") or None,
                remote=bool(item.get("isRemote")),
                url=item.get("jobUrl") or item.get("applyUrl") or "",
                source=f"{SOURCE_PREFIX}:{company}",
                posted_at=datetime.fromisoformat(item["publishedAt"]),
                raw_description=description[:6000],
                equity_mentioned=equity_mentioned(description),
            )
        )
    return jobs


def fetch() -> list[RawJob]:
    jobs: list[RawJob] = []
    with get_client() as client:
        for company in load_slugs("ashby"):
            try:
                jobs.extend(_fetch_company(client, company))
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                logger.warning("ashby:%s failed: %s", company, exc)
    return jobs
