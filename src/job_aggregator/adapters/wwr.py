"""We Work Remotely — public combined RSS feed, all categories. Titles are
formatted "Company: Job Title"; every listing is remote by definition."""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser

from job_aggregator.adapters.base import AdapterError, equity_mentioned, strip_html
from job_aggregator.storage.models import RawJob

SOURCE = "wwr"
FEED_URL = "https://weworkremotely.com/remote-jobs.rss"


def _split_title(raw_title: str) -> tuple[str, str]:
    if ":" in raw_title:
        company, _, title = raw_title.partition(":")
        return company.strip()[:200], title.strip()[:200]
    return "Unknown", raw_title.strip()[:200]


def fetch() -> list[RawJob]:
    feed = feedparser.parse(FEED_URL)
    if feed.bozo and not feed.entries:
        raise AdapterError(f"wwr: feed parse error: {feed.get('bozo_exception')}")

    jobs = []
    for entry in feed.entries:
        company, title = _split_title(entry.get("title", ""))
        description = strip_html(entry.get("summary", ""))

        published = entry.get("published_parsed")
        posted_at = (
            datetime(*published[:6], tzinfo=timezone.utc) if published else datetime.now(timezone.utc)
        )

        entry_id = entry.get("id") or entry.get("link") or ""
        jobs.append(
            RawJob(
                id=entry_id,
                title=title or "Untitled role",
                company=company,
                location=entry.get("region") or None,
                remote=True,
                url=entry.get("link", ""),
                source=SOURCE,
                posted_at=posted_at,
                raw_description=description[:6000],
                equity_mentioned=equity_mentioned(description),
            )
        )
    return jobs
