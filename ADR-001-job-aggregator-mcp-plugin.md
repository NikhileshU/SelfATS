# ADR-001: Job Aggregator MCP Plugin — CV-Matched, Multi-Source Job Discovery for Claude

**Status:** Proposed
**Date:** 2026-07-09
**Deciders:** Nikhilesh (sole builder/owner)

## Context

Nikhilesh is actively job searching for Head of Product / Technical PM / AI PM roles (full-time and freelance/fractional, ESOP-inclusive) and wants a tool, addable to Claude as an MCP plugin, that:

- Aggregates job listings across all company sizes (not just startups)
- Buckets listings by company stage/size
- Scores and suggests roles against an uploaded CV
- Separates listings that hard-gate on years-of-experience from those that don't
- Optionally drafts and (with per-listing confirmation) submits applications

**Key constraint:** LinkedIn, Wellfound, Underdog.io, and Built In are explicitly out of scope. None publish a usable public API, and pulling structured data from them requires either cookie-session browser automation or unofficial resellers — both violate platform ToS and risk account restriction. This was a deliberate scope cut, not an oversight, so no adapter, fallback, or "manual assist" path for these should be built.

**Non-functional constraints:**
- Single user, personal tool — not a multi-tenant service
- Low/zero hosting cost preferred (local-first)
- Builder is comfortable with Python, Docker/K8s, has shipped MCP-adjacent tools before (BeyondRoutes, EatEase)
- No urgency pressure beyond normal job-search timelines — correctness and maintainability matter more than speed-to-ship

## Decision

Build a **local, stdio-transport MCP server in Python**, backed by a **SQLite cache**, populated by a set of independent **source adapters** normalizing to a common job schema, with a **CV ingestion tool** that persists a parsed profile locally, a **rules + LLM-assisted scoring engine** for fit/stage/experience-gate classification, and an **application module** that only ever drafts and submits with explicit per-listing user confirmation.

## Components

```
claude (mcp client)
   │  stdio (JSON-RPC over stdin/stdout)
   ▼
mcp server (python, single process)
   │
   ├── tools/                     ← MCP tool definitions (the only client-facing surface)
   │     check_cv_status()
   │     set_cv(content)
   │     update_cv(content)
   │     search_jobs(filters)
   │     suggest_jobs(top_n)
   │     get_job_details(id)
   │     list_sources_status()
   │     refresh_cache(source?)
   │     draft_application(job_id)
   │     submit_application(job_id, confirmed=true)
   │
   ├── cv/
   │     parser.py                ← extracts structured profile from raw CV text
   │     store.py                 ← reads/writes cv_profile.json
   │
   ├── adapters/                  ← one file per source, common output schema
   │     hn_hiring.py
   │     remoteok.py
   │     remotive.py
   │     wwr.py
   │     yc_oss.py
   │     greenhouse.py / lever.py / ashby.py   (parameterized by company slug list)
   │     indeed.py / naukri.py    (only if a genuinely open access path is confirmed at build time)
   │
   ├── classify/
   │     stage_size.py            ← buckets: early-stage / pre-seed / seed / small / mid / large / MNC
   │     experience_gate.py       ← keyword+LLM heuristic: gated vs work-first
   │     fit_score.py             ← scores normalized job against cv_profile.json
   │
   ├── application/
   │     draft.py                 ← generates tailored resume emphasis + cover note
   │     submit_greenhouse.py / submit_lever.py / submit_ashby.py
   │
   ├── storage/
   │     jobs.db (SQLite)         ← normalized, deduped job cache
   │     cv_profile.json          ← persisted parsed CV
   │
   └── scheduler/
         refresh_job.py           ← invoked by GitHub Actions cron OR by refresh_cache tool
```

## Data flow (first-run and steady-state)

1. **Plugin added to Claude** → no CV on file yet.
2. User: *"find me Head of Product roles"* → Claude calls `suggest_jobs` → tool detects empty `cv_profile.json` → returns a structured "no CV" signal → Claude prompts user to upload a CV in chat.
3. User uploads CV → Claude extracts content → calls `set_cv(content)` → `cv/parser.py` structures it (roles, years, skills, tools, companies, projects) → persisted to `cv_profile.json`.
4. User re-asks / Claude retries `suggest_jobs` → server reads `jobs.db` (populated by adapters, refreshed on a TTL or cron schedule) → runs `stage_size.py`, `experience_gate.py`, `fit_score.py` over the cached set → returns ranked, bucketed, split results.
5. User: *"draft an application for job X"* → `draft_application(job_id)` returns the exact payload (resume emphasis, cover note, target fields) for review.
6. User confirms in chat → Claude calls `submit_application(job_id, confirmed=true)` → only then does a platform-specific submit adapter fire, and only for Greenhouse/Lever/Ashby-backed listings. Everything else returns a send-ready draft with no submit path.

## Options Considered

### Cache refresh: On-demand TTL vs. Scheduled cron

| Dimension | On-demand TTL | Scheduled cron (GitHub Actions) |
|---|---|---|
| Complexity | Low | Medium (needs a repo + Actions setup) |
| Query latency | Higher on cache miss (live fetch) | Always fast (reads local cache) |
| Rate-limit exposure | Spiky, tied to usage | Smooth, predictable, one run/day |
| Staleness | Fresher on demand | Up to 24h stale |
| Precedent | — | Matches `yc-oss/api`'s proven pattern |

**Decision: Scheduled cron**, mirroring `yc-oss/api`. Predictable load on sources, fast tool responses, and matches a pattern already proven to work against similar sources. On-demand `refresh_cache` tool remains available as a manual override.

### Storage: SQLite vs. flat JSON

| Dimension | SQLite | Flat JSON |
|---|---|---|
| Query flexibility | High (filter/sort/dedupe via SQL) | Low (full scan + in-memory filter) |
| Concurrency | Handles single-writer/multi-reader fine | Risk of partial writes if not careful |
| Portability | Single file, zero external deps | Single file, zero external deps |
| Fit for dedup logic | Natural (unique constraints) | Manual dedup logic needed |

**Decision: SQLite.** Job dedup (same role posted on multiple boards) and multi-dimension filtering (stage + remote + experience-gate + fit score) are exactly what SQL is for, and it stays a single-file, zero-infra dependency — no change to the local-first posture.

### CV fit-scoring: Pure heuristic vs. LLM-assisted

| Dimension | Pure heuristic (keyword/regex) | LLM-assisted (Claude call at scoring time) |
|---|---|---|
| Cost | Free | Small per-query cost |
| Accuracy on nuance | Weak (misses "AI PM" ≈ "Technical PM" type equivalence) | Strong |
| Explainability | High | Needs the model to state its reasoning |
| Latency | Instant | Adds a round-trip per batch |

**Decision: Hybrid.** Cheap heuristics (title keyword match, years-mentioned regex, stage keywords) do the first-pass filter to shrink the candidate set; an LLM-assisted pass (calling out to Claude, since this *is* a Claude plugin) handles the qualitative fit judgment and the "gated vs. work-first" classification on the shortlist only — not the full firehose. This keeps cost and latency bounded while getting real judgment where it matters.

### Transport: stdio (local) vs. HTTP (remote)

**Decision: stdio, local-first**, per earlier discussion — this is a single-user personal tool; remote hosting adds auth and infra complexity with no corresponding benefit yet. Revisit only if this becomes multi-device or shared.

## Trade-off Analysis

The core tension is **coverage vs. maintenance burden**. Every additional source adapter (Indeed, Naukri, more ATS platforms) adds discovery surface but also adds a thing that silently breaks when a site changes its markup or API shape — this is explicitly why `list_sources_status()` and `refresh_job.py` need per-source error isolation (one broken adapter shouldn't take down the aggregation run). Start with the confirmed-open sources (HN, RemoteOK, Remotive, WWR, yc-oss, Greenhouse/Lever/Ashby) and treat Indeed/Naukri as a stretch addition gated on verifying real open access at build time, not assumed now.

The second tension is **automation vs. control** on the application module. Full auto-apply would be faster but is explicitly rejected — per-listing confirmation is a deliberate design constraint, not a limitation to engineer around later.

## Consequences

- **Easier:** discovering relevant listings across a wider net than manual browsing; consistent CV-based scoring instead of re-reading every listing manually; drafting applications stops being a from-scratch task each time.
- **Harder:** each source adapter is a maintenance liability (markup/API drift); stage/size classification for non-startup companies (MNC, large, mid) has no clean open data source and will need its own heuristic or a paid data API (e.g., Crunchbase) if precision matters.
- **Revisit later:** whether Indeed/Naukri adapters are viable at all; whether the LLM-assisted scoring pass needs its own cost cap as job volume grows; whether cron-based refresh needs to move to a queue/webhook model if sources start rate-limiting the daily pull.

## Action Items

1. [ ] Scaffold repo structure (`tools/`, `adapters/`, `classify/`, `cv/`, `application/`, `storage/`, `scheduler/`)
2. [ ] Build HN + yc-oss adapters first (both fully open, no ToS ambiguity) as the vertical slice
3. [ ] Build `cv/parser.py` + `set_cv`/`check_cv_status` tools — this unblocks everything downstream
4. [ ] Build SQLite schema + dedup logic in `storage/jobs.db`
5. [ ] Add RemoteOK, Remotive, WWR, Greenhouse/Lever/Ashby adapters
6. [ ] Build `classify/stage_size.py`, `experience_gate.py`, `fit_score.py`
7. [ ] Wire GitHub Actions cron for scheduled refresh
8. [ ] Build `draft_application` + confirm-gated `submit_application` for Greenhouse/Lever/Ashby only
9. [ ] Verify Indeed/Naukri access paths before committing adapter effort there
10. [ ] Write Claude Desktop config snippet + README for plugin install
