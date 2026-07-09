"""Lever — semi-public JSON board endpoints, one company per API call.
Companies with no active Lever board return {"ok": false} (404), which is
expected and just yields zero jobs for that slug, not an adapter failure."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from job_aggregator.adapters.base import equity_mentioned, get_client, strip_html
from job_aggregator.adapters.company_boards import load_slugs
from job_aggregator.storage.models import RawJob

SOURCE_PREFIX = "lever"
BOARD_URL = "https://api.lever.co/v0/postings/{company}?mode=json"

logger = logging.getLogger(__name__)


def _fetch_company(client: httpx.Client, company: str) -> list[RawJob]:
    resp = client.get(BOARD_URL.format(company=company))
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return []

    jobs = []
    for item in data:
        description = strip_html(
            f"{item.get('descriptionPlain', '')}\n{item.get('additionalPlain', '')}"
        )
        categories = item.get("categories", {}) or {}
        location = categories.get("location")
        workplace_type = (item.get("workplaceType") or "").lower()
        jobs.append(
            RawJob(
                id=str(item["id"]),
                title=item.get("text", "")[:200] or "Untitled role",
                company=company,
                location=location,
                remote=workplace_type == "remote" or "remote" in (location or "").lower(),
                url=item.get("hostedUrl") or item.get("applyUrl") or "",
                source=f"{SOURCE_PREFIX}:{company}",
                posted_at=datetime.fromtimestamp(item["createdAt"] / 1000, tz=timezone.utc),
                raw_description=description[:6000],
                equity_mentioned=equity_mentioned(description),
            )
        )
    return jobs


def fetch() -> list[RawJob]:
    jobs: list[RawJob] = []
    with get_client() as client:
        for company in load_slugs("lever"):
            try:
                jobs.extend(_fetch_company(client, company))
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                logger.warning("lever:%s failed: %s", company, exc)
    return jobs
