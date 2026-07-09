"""Refreshes the job cache: runs every source adapter, upserts results,
refreshes the yc-oss company enrichment table, then runs the heuristic
classification pass. Invoked by the GitHub Actions cron
(.github/workflows/refresh.yml) or on-demand via the refresh_cache MCP tool.

Each adapter is isolated — one source's failure is recorded and skipped,
never aborts the run (ADR-001: "one broken adapter shouldn't take down the
aggregation run").
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from job_aggregator.adapters import ADAPTERS
from job_aggregator.adapters import yc_oss
from job_aggregator.classify.pipeline import run_heuristic_classification
from job_aggregator.storage import db

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def refresh_all(db_path: Path | str = db.DEFAULT_DB_PATH, sources: Optional[list[str]] = None) -> dict:
    """Returns {"sources": {name: {...stats}}, "classified": n}."""
    targets = sources or list(ADAPTERS.keys())
    unknown = set(targets) - set(ADAPTERS.keys())
    if unknown:
        raise ValueError(f"unknown source(s): {sorted(unknown)}. Known: {sorted(ADAPTERS.keys())}")

    results: dict[str, dict] = {}
    with db.connect(db_path) as conn:
        for name in targets:
            try:
                raw_jobs = ADAPTERS[name]()
                stats = db.upsert_raw_jobs(conn, raw_jobs)
                db.record_source_run(conn, name, "ok", jobs_found=stats["seen"], jobs_new=stats["new"])
                results[name] = {"status": "ok", **stats}
            except Exception as exc:  # noqa: BLE001 - per-source isolation is the point
                logger.warning("source %s failed: %s", name, exc)
                db.record_source_run(conn, name, "error", error=str(exc))
                results[name] = {"status": "error", "error": str(exc)}

        try:
            yc_count = yc_oss.refresh(conn)
            results["yc"] = {"status": "ok", "companies": yc_count}
        except Exception as exc:  # noqa: BLE001
            logger.warning("yc-oss enrichment refresh failed: %s", exc)
            results["yc"] = {"status": "error", "error": str(exc)}

        classified = run_heuristic_classification(conn)

    return {"sources": results, "classified": classified}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Refresh the job aggregator cache")
    parser.add_argument("--source", action="append", help="Limit to one source (repeatable)")
    args = parser.parse_args()

    result = refresh_all(sources=args.source)
    for name, stats in result["sources"].items():
        logger.info("%s: %s", name, stats)
    logger.info("classified %d jobs", result["classified"])


if __name__ == "__main__":
    main()
