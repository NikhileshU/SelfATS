# job-aggregator-mcp

A local, stdio-transport MCP server for CV-matched, multi-source job discovery — built as a personal Claude plugin. Design background: [ADR-001](ADR-001-job-aggregator-mcp-plugin.md) and the [handoff brief](handoff-brief-job-aggregator-mcp.md).

Aggregates listings from Hacker News "Who is Hiring", RemoteOK, Remotive, We Work Remotely, and a configurable list of Greenhouse/Lever/Ashby company boards; dedupes them into a local SQLite cache; classifies each by company stage and experience-gating; scores them against your CV; and drafts (never auto-submits) application materials.

**Explicitly out of scope:** LinkedIn, Wellfound, Underdog.io, Built In. None have a usable public API — pulling data from them means cookie-session browser automation or ToS-violating scraping. This was a deliberate cut, not a gap to fill later.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

That installs everything, including two console scripts inside `.venv`:
`job-aggregator-mcp` (the server) and `job-aggregator-refresh` (CLI cache refresh).

## Add to Claude Code (as a plugin)

The repo doubles as its own single-plugin marketplace:

```
/plugin marketplace add NikhileshU/SelfATS
/plugin install job-aggregator@selfats
```

(The repo is private, so your machine needs GitHub access git can use — `gh auth setup-git` covers that.) The plugin launches the server via `uv run`, so [uv](https://docs.astral.sh/uv/) must be on your PATH; dependencies sync automatically on first run.

Note: installing as a plugin clones a snapshot into `~/.claude/plugins/`, with its own copy of `jobs.db`. The `refresh_cache` tool hits live source APIs directly, so that copy stays fresh without needing plugin updates.

## Add to Gemini CLI (as an extension)

The repo also ships a `gemini-extension.json`, so [Gemini CLI](https://github.com/google-gemini/gemini-cli) users can install it directly:

```
gemini extensions install https://github.com/NikhileshU/SelfATS
```

Requires `uv` on PATH (same as the Claude paths). One behavioral difference:
the LLM-assisted fit-scoring pass uses MCP sampling, which Gemini CLI may not
support — scoring then falls back to heuristics automatically (title/skill
keyword match, years-gate regex, stage keywords). All tools otherwise work
identically.

## Add to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) and add:

```json
{
  "mcpServers": {
    "job-aggregator": {
      "command": "uv",
      "args": ["run", "--directory", "/Users/nikhilesh/Desktop/SelfATS", "job-aggregator-mcp"]
    }
  }
}
```

Restart Claude Desktop. Then in a chat: *"find me Head of Product roles"* — Claude will call `check_cv_status`, notice there's no CV yet, and ask you to paste your resume text.

## First run

The cache already has live data in it from development testing (Hacker News + the YC company directory). To pull everything else too:

```bash
uv run job-aggregator-refresh
```

Or ask Claude to call the `refresh_cache` tool. Either populates `src/job_aggregator/storage/jobs.db`.

## Tool surface

| Tool | Purpose |
|---|---|
| `check_cv_status()` | Is a CV on file? |
| `set_cv(content)` / `update_cv(content)` | Parse + persist resume text |
| `search_jobs(...)` | Filter the cache (stage, remote, experience_signal, keyword, source, min_fit_score) |
| `suggest_jobs(top_n)` | CV-ranked results, split by experience gating |
| `get_job_details(id)` | Full record for one job |
| `list_sources_status()` | Per-source refresh health |
| `refresh_cache(source?)` | Pull fresh listings (all sources, or one) |
| `draft_application(job_id)` | Tailored resume emphasis + cover note |
| `submit_application(job_id, confirmed)` | Opens the real application page — see below |

## Adding Greenhouse/Lever/Ashby companies

Edit `src/job_aggregator/storage/company_boards.json` — three arrays of company slugs, one per platform. Find a company's slug from its careers page URL:

- Greenhouse: `job-boards.greenhouse.io/{slug}` or `boards.greenhouse.io/{slug}`
- Lever: `jobs.lever.co/{slug}`
- Ashby: `jobs.ashbyhq.com/{slug}`

No code changes needed — the next `refresh_cache` picks up new entries. A wrong or defunct slug just yields zero jobs for that company; it doesn't break the run.

## Two deliberate deviations from the original design

**`yc-oss/api` isn't a job-listing source.** Verified at build time: it serves YC's company directory (stage, team size, an `isHiring` flag) with no per-role title or description — there's no real job to point someone at. So `adapters/yc_oss.py` populates a separate `yc_companies` enrichment table that `classify/stage_size.py` looks up by company name, rather than emitting fake job listings.

**No ATS exposes a public "submit application" API.** Greenhouse and Lever both gate their submission endpoints behind the *hiring company's own private API key* — not something a candidate's tool can ever have. Ashby's public apply flow is an undocumented internal SPA endpoint; automating it would be the same ToS grey zone this project explicitly ruled out for LinkedIn. So `submit_application(confirmed=true)` opens the listing's real application page in your browser after you've reviewed the draft — nothing is auto-filled or auto-submitted.

## LLM-assisted scoring

The "LLM-assisted" half of the hybrid fit-scoring design (per ADR-001) runs via [MCP sampling](https://modelcontextprotocol.io/docs/concepts/sampling) — the server asks the *connected client's* model to judge fit, so no separate Anthropic API key is needed. If the client doesn't support sampling, `suggest_jobs` and `draft_application` silently fall back to heuristic-only scoring/drafting (title/skill keyword matching); nothing breaks, it's just less nuanced.

## Scheduled refresh (optional)

`.github/workflows/refresh.yml` runs `job-aggregator-refresh` daily and commits the updated `jobs.db` back to the repo — only useful if you push this repo to your own GitHub with Actions enabled. It's optional: the on-demand `refresh_cache` tool always works standalone, with zero GitHub dependency, by hitting the live source APIs directly.

## Tests

```bash
uv run pytest
```
