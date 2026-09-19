"""
MCP server exposing the KTP Discord relay for ad-hoc pulls by an agent.

The actual pagination/crawling is deterministic plain code in discord_relay.py
(re-run any time to catch up on new messages — nothing here routes message
fetching through the model). This server is a thin wrapper for interactive
use: peek at a channel, or kick off/resume a full crawl and get a summary
back (the full dump goes to a JSONL cache file on disk, not into the
response, since channel history can be large).

Run standalone:  python discord_mcp.py
Register:        claude mcp add discord-relay -- python <abs path>/discord_mcp.py
                  (or drop the bundled .mcp.json into the project)
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

import discord_relay as R

mcp = FastMCP("discord-relay")


@mcp.tool()
def fetch_page(channel_id: str, after: str = "0", limit: int = 100) -> list[dict]:
    """
    Fetch one raw page (<=100 messages) of channel history with id > after.
    after='0' (default) starts from the very beginning of the channel.
    Use the largest 'id' seen in the response as the next call's `after` to
    page forward. Messages come back newest-first within the page.
    """
    client = R.RelayClient()
    return [R.slim_message(m) for m in client.get_page(channel_id, after=after, limit=limit)]


@mcp.tool()
def crawl_channel(channel_id: str, max_pages: int | None = None) -> dict:
    """
    Deterministically crawl a channel's full history (resuming from any
    prior cache) and append new messages to data/raw_<channel_id>.jsonl.
    Returns a summary only -- read the cache file directly (or use
    extract_drafts.py) for the actual message data, to keep this response
    small.
    """
    cache_path = R.default_cache_path(channel_id)
    client = R.RelayClient()
    count = 0
    first_ts = last_ts = None
    for msg in client.crawl_channel(channel_id, cache_path=cache_path, max_pages=max_pages):
        count += 1
        first_ts = first_ts or msg["timestamp"]
        last_ts = msg["timestamp"]
    return {
        "channel_id": channel_id,
        "cache_path": cache_path,
        "messages_in_cache": count,
        "earliest": first_ts,
        "latest": last_ts,
    }


@mcp.tool()
def cache_status(channel_id: str) -> dict:
    """Report what's already cached for a channel without hitting the relay."""
    cache_path = R.default_cache_path(channel_id)
    if not os.path.exists(cache_path):
        return {"channel_id": channel_id, "cache_path": cache_path, "cached": False}
    count = 0
    first_ts = last_ts = None
    with open(cache_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            import json

            msg = json.loads(line)
            count += 1
            first_ts = first_ts or msg["timestamp"]
            last_ts = msg["timestamp"]
    return {
        "channel_id": channel_id,
        "cache_path": cache_path,
        "cached": True,
        "messages_in_cache": count,
        "earliest": first_ts,
        "latest": last_ts,
    }


if __name__ == "__main__":
    mcp.run()
