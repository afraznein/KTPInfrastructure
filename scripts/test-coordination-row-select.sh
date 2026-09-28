#!/usr/bin/env bash
# Tests the Repos-in-scope row selection inside coordination-check-reusable.yml.
#
# The awk is not copied here -- it is EXTRACTED from the workflow between the
# "--- BEGIN/END row-select ---" markers, so the test cannot pass while the
# shipped gate says something different. A missing marker, an empty program or
# a fixture count of zero is a hard failure, not a quiet skip.
set -u

WF="${1:-.github/workflows/coordination-check-reusable.yml}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

prog="$tmp/row-select.awk"
# Strip the shell wrapper: drop the `selection=$(awk ... '` opener and the
# closing `' "<state>")`, leaving the awk program itself.
awk '
  /--- BEGIN row-select ---/ { grab = 1; next }
  /--- END row-select ---/   { grab = 0; next }
  grab
' "$WF" \
  | sed -e "s/^ *selection=\$(awk -v want=.* -v pr=.* '\$//" \
        -e "s/^ *' \"[^\"]*\")\$//" > "$prog"

if ! grep -q 'Repos in scope' "$prog"; then
  echo "FAIL: could not extract the row-select awk from $WF (markers moved or renamed?)"
  exit 1
fi
if ! grep -q 'ambiguous' "$prog"; then
  echo "FAIL: extracted program is missing its END verdicts -- extraction is wrong"
  exit 1
fi

pass=0; fail=0
run() { # run <fixture> <repo> <pr>  -> "<mode> <blocked_by>"
  awk -v want="$2" -v pr="$3" -f "$prog" "$1" | tr '\n' ' ' | sed -e 's/ *$//'
}
expect() { # expect <label> <expected> <fixture> <repo> <pr>
  local got; got="$(run "$3" "$4" "$5")"
  if [ "$got" = "$2" ]; then
    pass=$((pass + 1)); printf 'ok   %s\n' "$1"
  else
    fail=$((fail + 1)); printf 'FAIL %s\n       want: [%s]\n       got:  [%s]\n' "$1" "$2" "$got"
  fi
}

# --- Fixtures -------------------------------------------------------------
# Shaped exactly like state/infra-hidden-value-plays.md: a stack where the
# FIRST row (#548) is blocked by the SECOND (#547). Selecting by repo alone
# and taking head -1 told #547 it was blocked by #547.
cat > "$tmp/stacked.md" <<'MD'
---
slug: fixture-stacked
status: active
---
# fixture-stacked

## Goal
| KTPInfrastructure | decoy | [#999](https://github.com/afraznein/KTPInfrastructure/pull/999) | open | dpl-dead |

## Repos in scope
| Repo | Branch | PR | Status | Blocked by |
|---|---|---|---|---|
| KTPInfrastructure | feat/a | [#548](https://github.com/afraznein/KTPInfrastructure/pull/548) | open | https://github.com/afraznein/KTPInfrastructure/pull/547 |
| KTPInfrastructure | feat/b | [#547](https://github.com/afraznein/KTPInfrastructure/pull/547) | open | — |
| KTPInfrastructure | feat/c | [#538](https://github.com/afraznein/KTPInfrastructure/pull/538) | merged | — |
| KTPAMXX | feat/d | [#54](https://github.com/afraznein/KTPAMXX/pull/54) | open | dpl-abcd |

## Merge order
nothing
MD

# One row, no blocker -- the shape of state/infra-control-plane.md.
cat > "$tmp/single.md" <<'MD'
## Repos in scope
| Repo | Branch | PR | Status | Blocked by |
|---|---|---|---|---|
| KTPInfrastructure | control-plane/x | [#501](https://github.com/afraznein/KTPInfrastructure/pull/501) | open | — |
MD

# One row that DOES carry a blocker -- must still be enforced for a PR with no row.
cat > "$tmp/single-blocked.md" <<'MD'
## Repos in scope
| Repo | Branch | PR | Status | Blocked by |
|---|---|---|---|---|
| KTPAMXX | feat/x | [#12](https://github.com/afraznein/KTPAMXX/pull/12) | open | dpl-e72e |
MD

# Several rows, none blocked: a PR with no row has nothing to inherit.
cat > "$tmp/multi-clear.md" <<'MD'
## Repos in scope
| Repo | Branch | PR | Status | Blocked by |
|---|---|---|---|---|
| keep-the-prac | feat/a | [#100](https://github.com/searse/keep-the-prac/pull/100) | merged | — |
| keep-the-prac | feat/b | [#101](https://github.com/searse/keep-the-prac/pull/101) | open | - |
MD

# --- The bug, and the fix -------------------------------------------------
expect "#547 selects its OWN row, not #548's"        "row —"        "$tmp/stacked.md" KTPInfrastructure 547
expect "#548 stays blocked by #547"                  "row https://github.com/afraznein/KTPInfrastructure/pull/547" \
                                                                    "$tmp/stacked.md" KTPInfrastructure 548
expect "#538 selects its own cleared row"            "row —"        "$tmp/stacked.md" KTPInfrastructure 538

# --- Selection cannot leak across cells or rows ---------------------------
# 547 appears in #548's Blocked-by cell; a whole-row match would find that row.
expect "a PR number in a Blocked-by cell is not a match" "row —"     "$tmp/stacked.md" KTPInfrastructure 547
# #54 must not match #548/#547 by prefix, and lives under a different repo.
expect "#54 does not prefix-match #548"              "row dpl-abcd" "$tmp/stacked.md" KTPAMXX 54
# A row outside "## Repos in scope" is not a row.
expect "decoy row above the section is ignored"      "ambiguous"    "$tmp/stacked.md" KTPInfrastructure 999

# --- Single-row repos behave exactly as before ----------------------------
expect "single row, PR listed, matched by number"    "row —"        "$tmp/single.md" KTPInfrastructure 501
expect "single row, PR not listed, no blocker"       "single —"     "$tmp/single.md" KTPInfrastructure 777
expect "single row, PR not listed, blocker enforced" "single dpl-e72e" "$tmp/single-blocked.md" KTPAMXX 777

# --- No row for the PR ----------------------------------------------------
expect "several rows, one blocked, PR unlisted -> refuse" "ambiguous" "$tmp/stacked.md" KTPInfrastructure 601
expect "several rows, none blocked, PR unlisted -> pass"  "clear"     "$tmp/multi-clear.md" keep-the-prac 601
expect "repo absent from the table -> refuse"            "none"      "$tmp/single.md" KTPAntiCheat 501

# --- A non-numeric PR must not reach the dynamic regex --------------------
expect "non-numeric pr falls back, never compiles"   "ambiguous"    "$tmp/stacked.md" KTPInfrastructure "5[4"

# --- Is a Blocked-by cell resolvable at all? ------------------------------
# The regex is read out of the workflow, so a guard that stops matching a real
# cell form fails here rather than in production. Cells below are verbatim from
# ktp-coordination state files.
refs_only=$(sed -n "/--- BEGIN refs-only ---/,/--- END refs-only ---/p" "$WF" \
  | sed -n "s/^ *refs_only='\(.*\)'$/\1/p")
if [ -z "$refs_only" ]; then
  echo "FAIL: could not read the refs_only guard out of $WF"
  exit 1
fi

cell() { # cell <label> <resolvable|prose> <blocked_by cell>
  local got=prose
  printf '%s' "$3" | grep -qE "$refs_only" && got=resolvable
  if [ "$got" = "$2" ]; then
    pass=$((pass + 1)); printf 'ok   %s\n' "$1"
  else
    fail=$((fail + 1)); printf 'FAIL %s\n       want: [%s]\n       got:  [%s]\n' "$1" "$2" "$got"
  fi
}
cell "dpl- id is resolvable"          resolvable "dpl-bd55"
cell "#809 is resolvable"             resolvable "#809"
cell "bare 547 is resolvable"         resolvable "547"
cell "a pull URL is resolvable"       resolvable "https://github.com/afraznein/KTPInfrastructure/pull/547"
cell "two refs in one cell"           resolvable "dpl-bd55 #810"
cell "a sentence is refused"          prose      "the operator's retail-client confirmation, and the four-surface disclosure sync"
cell "a sentence with a number in it" prose      "operator apply of 20261014090000; a proven live DM"

# The gh field regression that made every PR block answer "unknown".
# Comments are stripped first: this file documents the defect by name.
if grep -v '^[[:space:]]*#' "$WF" | grep -q -- '--json merged'; then
  fail=$((fail + 1)); echo "FAIL gh pr view still asks for the non-existent --json field 'merged'"
else
  pass=$((pass + 1)); echo "ok   gh pr view does not ask for the non-existent --json field 'merged'"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
if [ "$pass" -lt 21 ]; then
  echo "FAIL: fewer cases ran than this harness defines -- assertions were lost, not satisfied"
  exit 1
fi
[ "$fail" -eq 0 ] || exit 1
