"""Registry of job-listing source adapters. Each entry maps a source name to
a zero-arg fetch() -> list[RawJob] callable. refresh_job.py iterates this
with per-source error isolation — see that module for why.

yc_oss is deliberately excluded: it's a company-enrichment source (stage,
team size), not a job-listing source. See adapters/yc_oss.py.
"""
from __future__ import annotations

from typing import Callable

from job_aggregator.adapters import ashby, greenhouse, hn_hiring, lever, remoteok, remotive, wwr
from job_aggregator.storage.models import RawJob

ADAPTERS: dict[str, Callable[[], list[RawJob]]] = {
    hn_hiring.SOURCE: hn_hiring.fetch,
    remoteok.SOURCE: remoteok.fetch,
    remotive.SOURCE: remotive.fetch,
    wwr.SOURCE: wwr.fetch,
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
}
