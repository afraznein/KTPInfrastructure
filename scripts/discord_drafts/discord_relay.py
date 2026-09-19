"""
Deterministic client + crawler for the KTP Discord relay.

This module does the actual HTTP paging itself (plain code, no LLM in the
loop) so a full-history crawl is a repeatable, resumable operation you can
re-run any time new match messages show up.

Env vars (see .env.example):
  DISCORD_RELAY_URL    base URL of the relay, e.g. https://discord-relay-xxx.run.app
  DISCORD_RELAY_TOKEN  value sent as the X-Relay-Auth header

A `.env` file (KEY=VALUE per line) next to this module is loaded automatically
if present, so the token never has to live in code or shell history.

CLI:
    python discord_relay.py crawl <channel_id> [--cache PATH] [--max-pages N]
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RELAY_URL = "https://discord-relay-78814186981.us-central1.run.app"
PAGE_LIMIT = 100  # hard cap enforced by Discord's own message-list endpoint


def _load_dotenv(path: str = os.path.join(HERE, ".env")) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()


class RelayError(RuntimeError):
    pass


def default_cache_path(channel_id: str) -> str:
    return os.path.join(HERE, "data", f"raw_{channel_id}.jsonl")


def _slim_user(u: dict | None) -> dict | None:
    if not u:
        return None
    return {"id": u.get("id"), "username": u.get("username"), "global_name": u.get("global_name")}


def slim_message(m: dict) -> dict:
    """Keep only the fields the extractor / a reviewer actually needs; drop
    avatar hashes, nameplates, clan cosmetics, etc."""
    slim = {
        "id": m["id"],
        "channel_id": m.get("channel_id"),
        "timestamp": m.get("timestamp"),
        "edited_timestamp": m.get("edited_timestamp"),
        "content": m.get("content", ""),
        "author": _slim_user(m.get("author")),
        "mentions": [_slim_user(u) for u in m.get("mentions", [])],
        "reactions": [
            {"name": r.get("emoji", {}).get("name"), "count": r.get("count")}
            for r in m.get("reactions", [])
        ],
    }
    ref = m.get("referenced_message")
    if ref:
        slim["referenced_message"] = {
            "id": ref.get("id"),
            "content": ref.get("content", ""),
            "author": _slim_user(ref.get("author")),
            "mentions": [_slim_user(u) for u in ref.get("mentions", [])],
        }
    return slim


class RelayClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.environ.get("DISCORD_RELAY_URL") or DEFAULT_RELAY_URL).rstrip("/")
        self.token = token or os.environ.get("DISCORD_RELAY_TOKEN")
        if not self.token:
            raise RelayError(
                "DISCORD_RELAY_TOKEN is not set. Copy .env.example to .env and fill it in, "
                "or export it in your shell."
            )

    def get_page(self, channel_id: str, after: str = "0", limit: int = PAGE_LIMIT) -> list[dict]:
        """One raw page from the relay, `limit` most-recent messages with id > after."""
        qs = urllib.parse.urlencode({"channelId": channel_id, "after": after, "limit": limit})
        url = f"{self.base_url}/messages?{qs}"
        req = urllib.request.Request(url, headers={"X-Relay-Auth": self.token})
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 4:
                    retry_after = float(e.headers.get("Retry-After", "2"))
                    time.sleep(retry_after)
                    continue
                raise RelayError(f"relay HTTP {e.code}: {e.read().decode('utf-8', 'replace')}") from e
        raise RelayError("relay: exhausted retries after repeated 429s")

    def crawl_channel(
        self,
        channel_id: str,
        cache_path: str | None = None,
        max_pages: int | None = None,
        sleep_s: float = 0.3,
    ):
        """
        Yield every message in the channel, oldest-first: replayed from
        cache_path (if it exists) then newly fetched from the relay forward
        to 'now'. New messages are appended to cache_path as JSONL as they're
        fetched, so re-running this only pulls what's new since last time.
        """
        seen_ids: set[str] = set()
        after = "0"

        if cache_path and os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    msg = json.loads(line)
                    seen_ids.add(msg["id"])
                    yield msg
            if seen_ids:
                after = str(max(int(i) for i in seen_ids))

        out = None
        if cache_path:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            out = open(cache_path, "a", encoding="utf-8")

        pages = 0
        try:
            while True:
                page = self.get_page(channel_id, after=after)
                if not page:
                    break
                for msg in sorted(page, key=lambda m: int(m["id"])):
                    if msg["id"] in seen_ids:
                        continue
                    slim = slim_message(msg)
                    seen_ids.add(slim["id"])
                    if out:
                        out.write(json.dumps(slim, ensure_ascii=False) + "\n")
                    yield slim
                after = str(max(int(m["id"]) for m in page))
                pages += 1
                if max_pages and pages >= max_pages:
                    break
                if len(page) < PAGE_LIMIT:
                    break  # caught up to the present
                if out:
                    out.flush()
                time.sleep(sleep_s)
        finally:
            if out:
                out.close()


def _cli():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    crawl = sub.add_parser("crawl", help="crawl full (or incremental) channel history to a JSONL cache")
    crawl.add_argument("channel_id")
    crawl.add_argument("--cache", default=None, help="cache file path (default: data/raw_<channel_id>.jsonl)")
    crawl.add_argument("--max-pages", type=int, default=None)

    args = ap.parse_args()
    if args.cmd == "crawl":
        cache_path = args.cache or default_cache_path(args.channel_id)
        client = RelayClient()
        count = 0
        first_ts = last_ts = None
        for msg in client.crawl_channel(args.channel_id, cache_path=cache_path, max_pages=args.max_pages):
            count += 1
            first_ts = first_ts or msg["timestamp"]
            last_ts = msg["timestamp"]
            if count % 200 == 0:
                print(f"...{count} messages ({last_ts})")
        print(f"done: {count} messages total in cache, {first_ts} .. {last_ts}")
        print(f"cache: {cache_path}")


if __name__ == "__main__":
    _cli()
