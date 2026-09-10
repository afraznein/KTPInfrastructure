"""Build identity_merges.json from the anti-cheat identity system
(ktp_ac_identities / ktp_ac_identity_links) instead of waiting on the
website's player_claim -- this is a real, operator-adjudicated, already-
granted source: 42 identities, ~71 steam_id links, most confirmed via
shared hardware ID, in-person LAN confirmation, or explicit operator
ruling. Some links are self-flagged as heuristic-only in their own
evidence text ("WEAKER KEY", "accepted in a batch, not independently
verified per pair") -- those are kept OUT of the applied merge file and
written to a separate review list instead, same discipline as everywhere
else in this project: never silently fold an uncertain identity into a
rating.

Steam ID format note: hlstats_PlayerUniqueIds stores "authserver:accountid"
(e.g. "1:NNNNNNNN"); the AC tables store the full "STEAM_0:1:NNNNNNNN" /
"STEAM_1:1:NNNNNNNN" form. The universe digit (STEAM_0 vs STEAM_1) does not
change the account -- same normalization rule already documented in the
website's SCHEMA.md for this exact quirk. Normalize both to the trailing
"Y:Z" before matching.
"""
import csv, json
from pathlib import Path

DATA = Path(__file__).parent / "data"
WEAK_MARKERS = ("WEAKER KEY", "not independently verified per pair", "Qualifier added")


def normalize(steam_id: str) -> str:
    parts = steam_id.replace("STEAM_", "").split(":")
    return ":".join(parts[-2:])  # authserver:accountid, universe digit dropped


def main():
    steam_to_pid = {}
    for r in csv.DictReader(open(DATA / "hlstats_player_unique_ids.tsv"), delimiter="\t"):
        if r["uniqueId"] == "HLTV":
            continue
        steam_to_pid[normalize(r["uniqueId"])] = int(r["playerId"])

    identities = {}
    for r in csv.DictReader(open(DATA / "ac_identity_links.tsv"), delimiter="\t"):
        identities.setdefault(r["identity_id"], []).append(r)

    merges, candidates, unresolved = {}, [], []
    for iid, rows in identities.items():
        mains = [r for r in rows if r["role"] == "main"]
        if len(mains) != 1:
            unresolved.append((iid, rows[0]["display_name"], f"{len(mains)} main rows"))
            continue
        main = mains[0]
        main_pid = steam_to_pid.get(normalize(main["steam_id"]))
        for r in rows:
            if r is main:
                continue
            alt_pid = steam_to_pid.get(normalize(r["steam_id"]))
            if alt_pid is None or main_pid is None or alt_pid == main_pid:
                continue  # nothing to merge: alt never played, or already unified
            weak = any(m in r["evidence"] for m in WEAK_MARKERS)
            entry = dict(identity=r["display_name"], alt_pid=alt_pid, main_pid=main_pid,
                         role=r["role"], evidence=r["evidence"])
            if weak:
                candidates.append(entry)
            else:
                merges[str(alt_pid)] = str(main_pid)

    out = {"_comment": "player_id -> canonical player_id, sourced from ktp_ac_identity_links "
                       "(operator-confirmed pairs only; see identity_merges_from_ac.py). "
                       "Weaker/heuristic-only links are in IDENTITY_MERGE_CANDIDATES.md, "
                       "not applied here."}
    out.update(merges)
    Path(DATA / "identity_merges.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    lines = ["# Identity merge candidates -- weak/heuristic, NOT applied (2026-09-07)\n",
             "These come from ktp_ac_identity_links but self-flag their own evidence as",
             "heuristic-only (shared name / consecutive Steam ID / batch ruling, not",
             "independently verified per pair). Not folded into identity_merges.json --",
             "review individually before applying. See ktp_ac_identity_links.evidence for",
             "the full reasoning per row.\n",
             "| Identity | Alt PID | Main PID | Role | Evidence |", "|---|---|---|---|---|"]
    for c in candidates:
        ev = c["evidence"].replace("|", "\\|")
        lines.append(f"| {c['identity']} | {c['alt_pid']} | {c['main_pid']} | {c['role']} | {ev} |")
    Path(__file__).with_name("IDENTITY_MERGE_CANDIDATES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{len(merges)} merges applied to identity_merges.json")
    print(f"{len(candidates)} weak candidates written to IDENTITY_MERGE_CANDIDATES.md")
    if unresolved:
        print(f"{len(unresolved)} identities skipped (not exactly one main row): {unresolved}")


if __name__ == "__main__":
    main()
