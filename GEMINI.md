# job-aggregator

CV-matched, multi-source job discovery over open job boards.

## How to use these tools

- Call `check_cv_status` before `suggest_jobs` or `draft_application`. If no CV
  is on file, ask the user to paste their resume text and pass it to `set_cv`
  first — everything downstream needs a parsed CV profile.
- `suggest_jobs` returns ranked, stage-bucketed listings split into
  experience-gated vs. work-first. `search_jobs` is the unranked filter query.
- If the job cache looks stale or empty, run `refresh_cache` — it fetches live
  from the source APIs.
- `draft_application(job_id)` returns the exact application payload for the
  user to review. `submit_application` requires the user to have seen that
  draft and explicitly confirmed, and only works for Greenhouse/Lever/Ashby
  listings; for all other sources, deliver the draft only.
- Fit scores may be heuristic-only on this client (the LLM-assisted scoring
  pass uses MCP sampling, which not all clients support). Treat scores as a
  first-pass ranking and apply your own judgment on the shortlist.

## Out of scope by design

LinkedIn, Wellfound, Underdog.io, and Built In are deliberately excluded —
no public APIs, and scraping them violates their ToS. Do not attempt to fetch
from them or suggest workarounds.
