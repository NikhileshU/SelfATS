"""Shared helpers for source adapters. Each adapter is independent so a
markup/API change in one never takes down the others (see AdapterError)."""
from __future__ import annotations

import html
import re

import httpx

USER_AGENT = "job-aggregator-mcp/0.1 (personal job search tool, single user)"


class AdapterError(RuntimeError):
    """Raised by an adapter's fetch() on any failure; refresh_job.py catches
    this per-source so one broken adapter doesn't abort the whole run."""


def get_client(timeout: float = 20.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )


_TAG_BREAK_RE = re.compile(r"(?i)</?(p|br|div|li|ul|ol|h[1-6])[^>]*>")
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def strip_html(text: str) -> str:
    text = _TAG_BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


_EQUITY_RE = re.compile(r"\bequity\b|\bstock options?\b|\bESOP\b", re.IGNORECASE)


def equity_mentioned(text: str) -> bool:
    return bool(_EQUITY_RE.search(text))


def looks_remote(*texts: str) -> bool:
    combined = " ".join(t or "" for t in texts).lower()
    return "remote" in combined
