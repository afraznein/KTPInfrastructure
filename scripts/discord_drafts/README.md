# discord_drafts

_Moved from the local `ktp_stats/ktp_metadata` research checkout on 2026-09-19
(infra-ktpr-consolidation). Code only: the crawl cache under `data/` and `.env` are
gitignored here; re-crawl to regenerate. Pick/ban drafts are the team-formation input
the MMR/seeding work reads._

Tools for pulling KTP match-channel Discord history and extracting the
captains' pick/ban draft dumps into structured data.

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # fill in DISCORD_RELAY_TOKEN
```

## 1. Crawl the channel

Deterministic, resumable, plain-code pagination (not an AI reading each
message) -- re-run any time to pull only what's new since the last crawl:

```
python discord_relay.py crawl <channel_id>
```

Writes/appends to `data/raw_<channel_id>.jsonl`, one slimmed-down Discord
message per line (id, timestamp, author, content, mentions, reactions).

The same crawl is also available as an MCP tool (`crawl_channel`,
`cache_status`, `fetch_page`) via `discord_mcp.py` / the bundled `.mcp.json`,
for ad-hoc agent-driven pulls without dropping to the CLI.

## 2. Extract pick/ban drafts

Pure regex parsing over the cache -- no LLM involved, so it's auditable and
re-runnable:

```
python extract_drafts.py <channel_id>
```

Reads `data/raw_<channel_id>.jsonl`, writes to `data/`:

- `drafts.json` -- full structured records (teams, ordered pick/ban actions,
  decider map, match time, division, player mentions, raw content)
- `drafts.csv` -- one row per draft message
- `drafts_actions.csv` -- long format, one row per individual pick/ban action
- `drafts_needs_review.csv` -- drafts that didn't fully resolve (missing
  decider, team count != 2, no player mentions) -- check these by hand
  against `raw_content`

## Format notes

Captains' draft messages are free-typed and the format drifted across
seasons (emoji-only vs. "name + emoji" prefixes, case, decider written as
"X decider" / "X 3rd map" / an arrow chain "A -> B -> C", division headers
like `***SILVER***` or `-SILVER-`, several ways of writing match time). The
extractor handles the variants seen in the corpus so far; anything it can't
resolve confidently is flagged in `drafts_needs_review.csv` rather than
guessed at silently. If a new format shows up in a future season, extend the
regexes in `extract_drafts.py` (they're deliberately unmagical) and re-run
against the same `.jsonl` cache -- no need to re-crawl.
