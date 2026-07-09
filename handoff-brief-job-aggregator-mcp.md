# Handoff Brief: Job Aggregator MCP Plugin

*Companion to `ADR-001-job-aggregator-mcp-plugin.md`. This doc is the condensed "what and why" — read the ADR for full component architecture and trade-off reasoning.*

## Who this is for
Nikhilesh — Associate PM at Trinity Lifesciences (pharma analytics), ~5 yrs experience spanning engineering and PM (TCS, OneBanc, Zykrr, Virtual Diamond Boutique), strong AI/LLM product background (RAG pipelines, LLM eval, Claude/Gemini/OpenAI APIs). Job searching for Head of Product / Technical PM / AI PM roles, full-time or freelance/fractional, ESOP-inclusive.

## What to build
An MCP server (Python, stdio transport, local-first) installable as a Claude plugin that:
1. Aggregates job listings from multiple open sources
2. Buckets every listing by company stage/size
3. Scores listings against an uploaded CV and suggests ranked roles
4. Splits listings into experience-gated vs. work/portfolio-first
5. Drafts (and, only with explicit per-listing confirmation, submits) applications

## Explicitly out of scope
**LinkedIn, Wellfound, Underdog.io, Built In** — none have usable public APIs; pulling data from them requires cookie-session browser automation or ToS-violating scraping. This is a deliberate cut to avoid account-restriction risk, not a gap to fill later. No adapter, fallback, or "manual assist via Claude in Chrome" path should be built for these — they were considered and rejected.

## Sources to build against (confirmed open access)
- **Hacker News "Who's Hiring"** — official public API
- **RemoteOK** — public JSON API
- **Remotive** — public API
- **We Work Remotely** — public RSS
- **yc-oss/api** (`github.com/yc-oss/api`) — YC company directory via Algolia index, not scraping, updated daily via GitHub Actions
- **Greenhouse / Lever / Ashby** — semi-public JSON board endpoints (e.g. `boards-api.greenhouse.io/v1/boards/{company}/jobs`), parameterized by a company slug list
- **Indeed / Naukri** — *not confirmed*. Verify genuine open access (official API or RSS) before building; do not scrape if no clean path exists.

## Common job schema (adapter output contract)
```json
{
  "id": "string",
  "title": "string",
  "company": "string",
  "location": "string",
  "remote": true,
  "stage": "early-stage|pre-seed|seed|small|mid|large|mnc|unknown",
  "experience_signal": "explicit_years|skills_first|unclear",
  "min_years": null,
  "equity_mentioned": false,
  "salary_range": {"min": null, "max": null, "currency": null},
  "url": "string",
  "source": "hn|remoteok|remotive|wwr|yc|greenhouse:{company}|lever:{company}|ashby:{company}",
  "posted_at": "ISO8601",
  "raw_description": "string"
}
```

## Key architecture decisions (see ADR for full reasoning)
| Decision | Choice | Why |
|---|---|---|
| Cache refresh | Scheduled cron (GitHub Actions), daily | Predictable load, fast reads, matches yc-oss/api precedent |
| Storage | SQLite (`jobs.db`) | Native dedup + multi-dimension filtering via SQL |
| Fit scoring | Hybrid: heuristic first-pass filter, LLM-assisted judgment on shortlist | Bounded cost/latency, real judgment where it matters |
| Transport | stdio, local-first | Single-user tool, no hosting/auth complexity needed yet |
| Application submission | Draft-and-confirm only, never silent batch | Explicit design constraint, not a limitation to remove later |

## CV flow (must be built this way, not upfront-required)
1. Server has no CV on first run — any scoring tool call detects this and signals Claude to prompt the user to upload one in chat
2. User uploads CV in chat → Claude extracts content → calls `set_cv(content)`
3. Server parses and persists to `cv_profile.json` — reused across sessions
4. `update_cv` tool for resume changes later

## Core tool surface (MCP tools to expose)
```
check_cv_status()
set_cv(content)
update_cv(content)
search_jobs(filters)
suggest_jobs(top_n)
get_job_details(id)
list_sources_status()
refresh_cache(source?)
draft_application(job_id)
submit_application(job_id, confirmed=true)
```

## Application submission rule (non-negotiable)
`submit_application` only fires for Greenhouse/Lever/Ashby-backed listings with a real submission endpoint, and only after the user has seen the exact payload via `draft_application` and explicitly confirmed. All other sources (HN, RemoteOK, etc.) return a send-ready draft only — no submit path exists or should be built for them.

## Build order (from ADR Action Items)
1. Scaffold repo structure (`tools/`, `adapters/`, `classify/`, `cv/`, `application/`, `storage/`, `scheduler/`)
2. HN + yc-oss adapters first — fully open, zero ToS ambiguity, good vertical slice
3. `cv/parser.py` + `set_cv`/`check_cv_status` tools — unblocks everything downstream
4. SQLite schema + dedup logic
5. RemoteOK, Remotive, WWR, Greenhouse/Lever/Ashby adapters
6. `classify/stage_size.py`, `experience_gate.py`, `fit_score.py`
7. GitHub Actions cron for scheduled refresh
8. `draft_application` + confirm-gated `submit_application`
9. Verify Indeed/Naukri before committing effort there
10. Claude Desktop config snippet + README for plugin install

## Open questions to resolve during build
- Stage/size classification for **non-startup** companies (mid/large/MNC) has no clean open data source — will need a heuristic (headcount/domain lookup) or a paid API (Crunchbase) if precision matters. Revisit once the startup-side buckets are working.
- Indeed/Naukri viability — check before writing adapter code, don't assume.
