"""The weekly cast intake, in one command: find new casts, transcribe them, align them, clean up.

Pairs with `caster_align.py` (attach commentary to priced plays) and `caster_recall.py` (does the
pricing agree with a human watching). This is the job that keeps their corpus fed without anyone
remembering six steps in order.

  caster_weekly.py scan            list casts newer than the store knows; add them unplaced
  caster_weekly.py status          what is placed, fetched, aligned, and what waits on a human
  caster_weekly.py run [--cast ID] transcribe + export + align every cast that is ready
  caster_weekly.py run --dry-run   print the plan, touch nothing
  caster_weekly.py coverage        what share of officials the cast corpus actually covers

TWO THINGS IT DELIBERATELY WILL NOT DO, because both were measured wrong when automated:

  1. Place a cast against a match. Titles and times get you a shortlist; the transcript settles it.
     A cast started while a match was played is LIVE; one that was not is a DELAYED re-cast of an
     older match, and the two align completely differently.
  2. Find the half end in a delayed cast. Correlating spoken player names against that player's
     frags does not converge (~57% of mentions coincide at ANY offset; best margin 2 points of 60).
     A human reads the transcript for the moment the score is called and supplies `anchor`.

So `scan` writes a stub and stops. Fill in `matches` (and `anchor` for a delayed cast) and `run`
does the rest. `status` tells you which stubs are waiting on you.

CONSENT IS A PRECONDITION, not a convention. Nothing is downloaded until the store carries a
`_consent` string saying who agreed and when. Recordings are transcribed once and deleted in the
same step -- text only, always, including when the run fails partway.

CONFIGURATION, all through the environment, because none of it belongs in a public repo:

  KTP_CASTER_CASTS       the store, default caster/casts.json (see caster-casts.json.example)
  KTP_CASTER_TEXT_DIR    transcripts land here, default caster/text
  KTP_CASTER_EVENTS_DIR  match exports land here, default caster/events
  KTP_CASTER_CHANNELS    comma-separated channel URLs for `scan` (or "channels" in the store)
  KTP_CASTER_SQL         command that reads SQL on stdin and writes TSV on stdout, e.g.
                         'mysql -B hlstatsx' locally, or an ssh wrapper around it
  KTP_WHISPER_CLI        whisper.cpp binary, default whisper-cli
  KTP_WHISPER_MODEL      model path, default models/ggml-medium.en.bin
  KTP_YTDLP              yt-dlp invocation, default 'yt-dlp'
  KTP_FFMPEG             ffmpeg invocation, default 'ffmpeg'
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STORE = Path(os.environ.get("KTP_CASTER_CASTS", "caster/casts.json"))
TEXT = Path(os.environ.get("KTP_CASTER_TEXT_DIR", "caster/text"))
EVENTS = Path(os.environ.get("KTP_CASTER_EVENTS_DIR", "caster/events"))
WHISPER = os.environ.get("KTP_WHISPER_CLI", "whisper-cli")
MODEL = os.environ.get("KTP_WHISPER_MODEL", "models/ggml-medium.en.bin")
YTDLP = os.environ.get("KTP_YTDLP", "yt-dlp")
FFMPEG = os.environ.get("KTP_FFMPEG", "ffmpeg")
LIVE_OFFSET = "60"

QUERIES = {
    "frags": """SELECT f.event_epoch, f.game_time, f.half, f.eventTime,
        k.player_name AS killer, v.player_name AS victim, f.weapon, f.headshot, f.is_last_flag_defense
      FROM hlstats_Events_Frags f
      LEFT JOIN ktp_match_players k ON k.match_id=f.match_id AND k.player_id=f.killerId
      LEFT JOIN ktp_match_players v ON v.match_id=f.match_id AND v.player_id=f.victimId
      WHERE f.match_id='{m}' ORDER BY f.event_epoch, f.id""",
    "flag_state": """SELECT event_epoch, game_time, half, flag_index, flag_name, owner_team,
        is_initial, round_time_left, event_time
      FROM ktp_flag_state_events WHERE match_id='{m}' ORDER BY id""",
    "score": """SELECT s.event_epoch, s.game_time, s.half, p.player_name, s.delta, s.total,
        s.flag_name, s.event_time
      FROM ktp_score_events s
      LEFT JOIN ktp_match_players p ON p.match_id=s.match_id AND p.player_id=s.player_id
      WHERE s.match_id='{m}' ORDER BY s.id""",
}
ROSTER_Q = "SELECT DISTINCT player_name FROM ktp_match_players WHERE match_id='{m}'"
HALVES_Q = ("SELECT match_id, half, UNIX_TIMESTAMP(start_time) AS start_epoch, "
            "UNIX_TIMESTAMP(end_time) AS end_epoch FROM ktp_matches WHERE match_id IN ({ids}) "
            "ORDER BY match_id, half")


def watch_url(cid, channel_url):
    """Twitch ids come out of a listing as "v2885964510" but the watch URL takes the bare number;
    leaving the v on gives a page that resolves to nothing and looks like a cast with no start."""
    if "twitch" in channel_url:
        return f"https://www.twitch.tv/videos/{cid.lstrip('v')}"
    return f"https://www.youtube.com/watch?v={cid}"


def as_int(v):
    """yt-dlp prints numbers as floats ("6922.0") and "NA" when it has none."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def die(msg):
    sys.exit(f"caster_weekly: {msg}")


# Which env var supplies each external tool, so a missing one names its own fix.
TOOL_HINT = {"yt-dlp": "KTP_YTDLP", "ffmpeg": "KTP_FFMPEG", "whisper-cli": "KTP_WHISPER_CLI",
             "whisper": "KTP_WHISPER_CLI", "mysql": "KTP_CASTER_SQL", "ssh": "KTP_CASTER_SQL"}


def run(cmd, **kw):
    """Shell out. cmd may be a list, or a string when it carries the operator's own quoting."""
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", **kw)
    except FileNotFoundError:
        exe = Path(cmd[0]).name
        var = TOOL_HINT.get(exe, "")
        die(f"{exe!r} is not on PATH" + (f" — set {var} to how it is invoked here, "
            f"e.g. {var}='python -m yt_dlp'" if var else ""))


def load_store():
    if not STORE.exists():
        die(f"no store at {STORE} — copy scripts/caster-casts.json.example and fill it in")
    data = json.loads(STORE.read_text(encoding="utf-8"))
    if not str(data.get("_consent", "")).strip():
        die("the store has no `_consent` line. Nothing is downloaded until it says who agreed to "
            "being transcribed and when. This is a precondition, not paperwork.")
    return data


def save_store(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def casts(data):
    return {k: v for k, v in data.items() if not k.startswith("_")}


def sql(query):
    cmd = os.environ.get("KTP_CASTER_SQL")
    if not cmd:
        die("KTP_CASTER_SQL is unset — it must be a command that reads SQL on stdin and writes TSV")
    out = run(cmd, input=query)
    if out.returncode != 0:
        die(f"SQL failed: {(out.stderr or '').strip()[:300]}")
    return out.stdout


def state_of(cast_id, c):
    """What this cast is waiting for. The two human states are the point of the whole design."""
    if not c.get("matches"):
        return "needs placing"
    if not (TEXT / f"v{cast_id}.json").exists():
        return "ready to transcribe"
    # The anchor gate belongs HERE, not before transcription: a delayed cast's anchor is read out
    # of its own transcript (the moment the halftime score is called), so demanding it first made
    # the one thing that produces it unreachable.
    if c.get("kind") == "delayed":
        anchors = c.get("anchors") or ({m: c["anchor"] for m in c["matches"]} if c.get("anchor") else {})
        if any(m not in anchors for m in c["matches"]):
            return "needs an anchor"
    missing = [m for m in c["matches"] if not (EVENTS / f"{m}.frags.tsv").exists()]
    if missing:
        return "ready to export events"
    if all((TEXT / f"v{cast_id}.{m}.align.md").exists() for m in c["matches"]):
        return "done"
    return "ready to align"


# ---------------------------------------------------------------- scan
def cmd_scan(a):
    data = load_store()
    channels = [u.strip() for u in
                (os.environ.get("KTP_CASTER_CHANNELS") or ",".join(data.get("_channels", []))).split(",")
                if u.strip()]
    if not channels:
        die("no channels — set KTP_CASTER_CHANNELS or a `_channels` list in the store")
    known = set(casts(data))
    # The same cast is often on two channels under different ids. Matching title plus a duration
    # within a minute catches the mirror, so a week's scan does not propose transcribing a cast
    # already sitting in the store under its other id.
    fingerprints = {(c.get("title", "").strip().lower(), round(c.get("duration", 0) / 60))
                    for c in casts(data).values() if c.get("title")}
    # "Newer than the store knows": default the floor to the newest cast already placed, so a
    # channel's whole back catalogue is not proposed every week. A channel that lists no start
    # time (YouTube's flat listing does not) cannot be placed OR aligned, so those are skipped
    # and counted rather than written as stubs nobody can use.
    floor = a.since_epoch or max([c.get("start", 0) for c in casts(data).values()] or [0])
    found = undated = old = mirrored = 0
    for url in channels:
        cmd = [*shlex.split(YTDLP), "--flat-playlist", "--print",
               "%(id)s|%(timestamp)s|%(duration)s|%(title)s", url]
        if a.limit:
            cmd += ["--playlist-end", str(a.limit)]
        out = run(cmd)
        if out.returncode != 0:
            print(f"  ! {url}: {(out.stderr or '').strip().splitlines()[-1:]}")
            continue
        for line in out.stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue
            cid, ts, dur, title = parts
            # A Twitch listing id is "v2885964510"; the watch URL and every filename here use the
            # bare number, so normalise once at the door rather than stripping it in five places.
            if "twitch" in url and re.fullmatch(r"v\d+", cid):
                cid = cid[1:]
            if cid in known:
                continue
            start, dur_s = as_int(ts), as_int(dur)
            if not start:
                # A flat playlist listing carries no timestamp on Twitch OR YouTube -- every entry
                # comes back "NA". Skipping those silently discarded real casts and reported "0 new"
                # for a week. Resolve per candidate instead: one metadata call, no download, and
                # only for ids the store has never seen.
                meta = run([*shlex.split(YTDLP), "--skip-download", "--no-warnings",
                            "--print", "%(timestamp)s|%(duration)s", watch_url(cid, url)])
                if meta.returncode == 0 and meta.stdout.strip():
                    mt = meta.stdout.strip().splitlines()[-1].split("|")
                    start, dur_s = as_int(mt[0]), as_int(mt[1]) or dur_s
            if not start:
                undated += 1
                continue
            if start <= floor:
                old += 1
                continue
            fp = (title.strip().lower(), round(dur_s / 60))
            if fp in fingerprints or any(fp[0] == f[0] and abs(fp[1] - f[1]) <= 1 for f in fingerprints):
                mirrored += 1
                continue
            fingerprints.add(fp)
            data[cid] = {"start": start, "kind": "", "title": title, "duration": dur_s,
                         "url": watch_url(cid, url),
                         "source": url, "matches": {}}
            found += 1
            when = (datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d %H:%M")
                    if start else "unknown start")
            print(f"  + {cid}  {when}  {dur_s // 60}m  {title[:70]}")
    if found and not a.dry_run:
        save_store(data)
    when = (datetime.fromtimestamp(floor, timezone.utc).strftime("%Y-%m-%d") if floor else "the beginning")
    print(f"{found} new cast(s) since {when}"
          + (f"; {old} older skipped" if old else "")
          + (f"; {mirrored} mirror(s) of a cast already in the store skipped" if mirrored else "")
          + (f"; {undated} with no start time skipped (cannot be placed or aligned)" if undated else "")
          + ("" if a.dry_run else f" — written to {STORE}") +
          ("\nFill in `matches` (and `kind`/`anchor` for a delayed re-cast), then `run`."
           if found else ""))


# ---------------------------------------------------------------- run
def transcribe(cast_id, c, dry):
    """Pull audio, transcribe with the roster as the prompt, and delete the audio in the same step."""
    TEXT.mkdir(parents=True, exist_ok=True)
    roster = []
    for m in c["matches"]:
        roster += [r.strip() for r in sql(ROSTER_Q.format(m=m)).splitlines()[1:] if r.strip()]
    prompt = ("KTP Day of Defeat match cast. Players: " + ", ".join(sorted(set(roster))) + ".")[:900]
    audio = TEXT / f"v{cast_id}.m4a"
    wav = TEXT / f"v{cast_id}.16k.wav"
    if dry:
        print(f"    would fetch audio, transcribe with a {len(set(roster))}-name prompt, delete audio")
        return
    try:
        out = run([*shlex.split(YTDLP), "-q", "--no-progress", "-f", "bestaudio",
                   "-o", str(audio), c.get("url") or f"https://www.twitch.tv/videos/{cast_id}"])
        if out.returncode != 0 or not audio.exists():
            die(f"audio fetch failed for {cast_id}: {(out.stderr or '').strip()[:200]}")
        out = run([*shlex.split(FFMPEG), "-v", "error", "-y", "-i", str(audio),
                   "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
        if out.returncode != 0:
            die(f"ffmpeg failed for {cast_id}: {(out.stderr or '').strip()[:200]}")
        out = run([*shlex.split(WHISPER), "-m", MODEL, "-f", str(wav), "-l", "en",
                   "--prompt", prompt, "-oj", "-otxt", "-of", str(TEXT / f"v{cast_id}")])
        if out.returncode != 0 or not (TEXT / f"v{cast_id}.json").exists():
            die(f"transcription failed for {cast_id}: {(out.stderr or '').strip()[:200]}")
        print(f"    transcribed ({len(set(roster))} names in the prompt)")
    finally:
        # Text only, always -- including when the run died partway. This is the retention rule,
        # enforced rather than remembered.
        for f in (audio, wav):
            if f.exists():
                f.unlink()
                print(f"    deleted {f.name}")


def export_events(match_ids, dry):
    EVENTS.mkdir(parents=True, exist_ok=True)
    for m in match_ids:
        for name, q in QUERIES.items():
            dest = EVENTS / f"{m}.{name}.tsv"
            if dest.exists():
                continue
            if dry:
                print(f"    would export {dest.name}")
                continue
            dest.write_text(sql(q.format(m=m)), encoding="utf-8", newline="\n")
            print(f"    exported {dest.name} ({sum(1 for _ in dest.open(encoding='utf-8')) - 1} rows)")
    if dry:
        print("    would refresh halves.tsv")
        return
    ids = ", ".join(f"'{m}'" for m in match_ids)
    (EVENTS / "halves.tsv").write_text(sql(HALVES_Q.format(ids=ids)), encoding="utf-8", newline="\n")


def align(cast_id, c, dry):
    here = Path(__file__).resolve().parent
    for match_id, map_name in c["matches"].items():
        cmd = [sys.executable, str(here / "caster_align.py"), match_id, cast_id,
               "--vod-start", str(c["start"]), "--map", map_name]
        if c.get("kind") == "delayed":
            anchors = c.get("anchors") or {m: c.get("anchor") for m in c["matches"]}
            cmd += ["--anchor", anchors[match_id]]
        else:
            cmd += ["--offset", LIVE_OFFSET]
        dest = TEXT / f"v{cast_id}.{match_id}.align.md"
        if dry:
            print(f"    would run: {' '.join(cmd[1:])}")
            continue
        out = run(cmd)
        if out.returncode != 0:
            print(f"    ! align failed for {match_id}: {(out.stderr or '').strip()[:200]}")
            continue
        dest.write_text(out.stdout, encoding="utf-8", newline="\n")
        head = out.stdout.splitlines()[0] if out.stdout else ""
        print(f"    aligned {match_id} -> {dest.name}\n      {head[:150]}")


def cmd_run(a):
    data = load_store()
    todo = {k: v for k, v in casts(data).items() if not a.cast or k == a.cast}
    if not todo:
        die(f"no cast {a.cast} in the store")
    waiting, worked = [], 0
    for cast_id, c in sorted(todo.items(), key=lambda kv: kv[1].get("start", 0)):
        st = state_of(cast_id, c)
        if st == "needs placing":
            waiting.append((cast_id, st, c.get("title", "")))
            continue
        if st == "done":
            if a.cast:
                print(f"{cast_id} is already done — transcript and every alignment exist")
            continue
        print(f"{cast_id}  {c.get('title', '')[:60]}  [{st}]")
        if not (TEXT / f"v{cast_id}.json").exists():
            transcribe(cast_id, c, a.dry_run)
        export_events(list(c["matches"]), a.dry_run)
        if state_of(cast_id, c) == "needs an anchor":
            waiting.append((cast_id, "needs an anchor", c.get("title", "")))
            print("    transcribed and exported; alignment waits on the anchor — read the transcript "
                  "for where the halftime score is called and set `anchor`")
            continue
        align(cast_id, c, a.dry_run)
        worked += 1
        if a.table and not a.dry_run:
            row = (f"| [{cast_id}]({c.get('url', '')}) | "
                   f"{datetime.fromtimestamp(c['start'], timezone.utc).strftime('%Y-%m-%d %H:%M')} | "
                   f"{c.get('duration', 0)//3600}h{(c.get('duration', 0)%3600)//60:02d} | "
                   f"{c.get('title','')} | transcribed, audio deleted | "
                   f"{c.get('kind','live')}: {', '.join(c['matches'])} |  |  |\n")
            with open(a.table, "a", encoding="utf-8", newline="\n") as f:
                f.write(row)
            print(f"    appended a row to {a.table}")
    print(f"\n{worked} cast(s) processed" + (" (dry run)" if a.dry_run else ""))
    for cast_id, st, title in waiting:
        print(f"WAITING ON YOU: {cast_id} {st} — {title[:60]}")
    if waiting:
        print("Place a cast by filling `matches` ({match_id: map_name}); for a delayed re-cast set "
              "`kind` to \"delayed\", then after it transcribes read the transcript for where the "
              "halftime score is called and set `anchor` to that MM:SS.")


OFFICIALS_Q = ("SELECT COUNT(DISTINCT match_id) FROM ktp_matches "
               "WHERE match_type=0 AND start_time >= '{since}'")


def cmd_coverage(a):
    """Only matches that were cast can ever be checked this way, so any verdict drawn from this
    corpus has to be read against its share of the season. Printing it is the cheapest way to stop
    a subset being mistaken for the whole."""
    data = load_store()
    covered = {m for c in casts(data).values() for m in (c.get("matches") or {})}
    rows = [r for r in sql(OFFICIALS_Q.format(since=a.since)).splitlines()[1:] if r.strip()]
    total = int(rows[0]) if rows else 0
    pct = f"{len(covered) / total:.0%}" if total else "—"
    print(f"cast corpus covers {len(covered)} of {total} officials since {a.since} — {pct}")
    print("A verdict from this corpus is a verdict about the cast subset, never the season.")
    for m in sorted(covered):
        print(f"  {m}")


def cmd_status(a):
    data = load_store()
    rows = [(c.get("start", 0), cid, state_of(cid, c), c.get("title", "")) for cid, c in casts(data).items()]
    for start, cid, st, title in sorted(rows):
        when = datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%d") if start else "????-??-??"
        print(f"{when}  {cid:14} {st:22} {title[:60]}")
    print(f"\n{len(rows)} cast(s); consent on file: {data['_consent']}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--limit", type=int, default=25, help="list at most this many per channel (0 = all)")
    s.add_argument("--since", default="", help="YYYY-MM-DD floor; default is the newest cast in the store")
    s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("coverage")
    s.add_argument("--since", default="2026-09-13", help="season start, YYYY-MM-DD")
    s.set_defaults(fn=cmd_coverage)
    s = sub.add_parser("run")
    s.add_argument("--cast", default="")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--table", default="", help="append a row per processed cast to this markdown table")
    s.set_defaults(fn=cmd_run)
    a = ap.parse_args()
    if getattr(a, "since", ""):
        a.since_epoch = int(datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    elif a.cmd == "scan":
        a.since_epoch = 0
    a.fn(a)


if __name__ == "__main__":
    main()
