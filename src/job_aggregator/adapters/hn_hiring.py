"""Hacker News 'Who is hiring?' — official Algolia HN Search API, no scraping.

Each top-level comment on the latest monthly thread is one job posting.
Postings are free-text (no structured schema), typically formatted as
"Company | Role | Location | ..." — parsed heuristically on a best-effort
basis; classify/experience_gate.py and fit_score.py do the real judgment
work on raw_description afterward.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

from job_aggregator.adapters.base import (
    AdapterError,
    equity_mentioned,
    get_client,
    looks_remote,
    strip_html,
)
from job_aggregator.storage.models import RawJob

SOURCE = "hn"
ALGOLIA_BASE = "https://hn.algolia.com/api/v1"


def _latest_hiring_thread_id(client: httpx.Client) -> str:
    resp = client.get(
        f"{ALGOLIA_BASE}/search_by_date",
        params={"tags": "story,author_whoishiring", "hitsPerPage": 20},
    )
    resp.raise_for_status()
    for hit in resp.json()["hits"]:
        if hit.get("title", "").lower().startswith("ask hn: who is hiring"):
            return hit["objectID"]
    raise AdapterError("could not find a current 'Who is hiring?' thread")


def _fetch_top_level_comments(client: httpx.Client, story_id: str) -> list[dict]:
    comments: list[dict] = []
    page = 0
    story_id_int = int(story_id)
    while True:
        resp = client.get(
            f"{ALGOLIA_BASE}/search_by_date",
            params={"tags": f"comment,story_{story_id}", "hitsPerPage": 1000, "page": page},
        )
        resp.raise_for_status()
        data = resp.json()
        comments.extend(
            h for h in data["hits"]
            if h.get("parent_id") == story_id_int and h.get("comment_text")
        )
        page += 1
        if page >= data.get("nbPages", 1):
            break
    return comments


def _parse_comment(comment: dict) -> Optional[RawJob]:
    text = strip_html(comment.get("comment_text") or "")
    if not text:
        return None

    first_line = text.splitlines()[0]
    parts = [p.strip() for p in first_line.split("|") if p.strip()]
    if len(parts) >= 2:
        company, title = parts[0][:200], parts[1][:200]
        location = parts[2][:200] if len(parts) >= 3 else None
    else:
        company, title, location = "Unknown", first_line[:200] or "See listing", None

    posted_at = datetime.fromtimestamp(comment["created_at_i"], tz=timezone.utc)
    return RawJob(
        id=str(comment["objectID"]),
        title=title,
        company=company,
        location=location,
        remote=looks_remote(text),
        url=f"https://news.ycombinator.com/item?id={comment['objectID']}",
        source=SOURCE,
        posted_at=posted_at,
        raw_description=text[:6000],
        equity_mentioned=equity_mentioned(text),
    )


def fetch() -> list[RawJob]:
    try:
        with get_client() as client:
            story_id = _latest_hiring_thread_id(client)
            comments = _fetch_top_level_comments(client, story_id)
    except httpx.HTTPError as exc:
        raise AdapterError(f"hn_hiring: {exc}") from exc

    jobs = []
    for comment in comments:
        job = _parse_comment(comment)
        if job:
            jobs.append(job)
    return jobs
