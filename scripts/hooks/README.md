# Shared pre-push hooks for KTP plugin repos

This directory contains the **canonical** copies of pre-push lint scripts that
multiple KTP plugin repos consume. Each consumer's `scripts/pre-push.sh`
references these files by sibling-checkout path:

```sh
"$REPO_ROOT/../KTPInfrastructure/scripts/hooks/<lint-name>.sh"
```

## Why canonical, not per-repo copies

A regression-class lint (e.g. amxxcurl async-lifetime) only delivers value if
**every** consumer of the bug-prone API runs the same checks. Per-repo copies
drift: a fix or new pattern lands in one repo, the others stay on the old
version, and the next regression slips through the gap.

Single source of truth means:

- Update the lint here once → every consumer picks it up on next push (no
  reinstall, no rebuild — `pre-push.sh` resolves the path at hook-fire time)
- New anti-pattern? One PR adds it; full ecosystem coverage immediately
- Audit trail: `git log scripts/hooks/` shows the full history of what each
  lint catches and why

If you find a copy of one of these scripts inside another KTP repo, that's a
bug. Delete it and update the consumer's `pre-push.sh` to reference the
canonical here.

## Current hooks

| Script | What it catches | Affected repos |
|---|---|---|
| [`lint-amxxcurl-async.sh`](lint-amxxcurl-async.sh) | `curl_easy_cleanup` outside async-callback fns; `curl_slist_free_all` on a `g_*` global outside `plugin_end` | Any consumer of `ktp_discord.inc` or other amxxcurl-using shared includes |

## Consumer integration

A consumer's `scripts/pre-push.sh` typically looks like:

```sh
REPO_ROOT="$(git rev-parse --show-toplevel)"
INFRA_DIR="$REPO_ROOT/../KTPInfrastructure"
LINT="$INFRA_DIR/scripts/hooks/lint-amxxcurl-async.sh"

if [[ ! -x "$LINT" ]]; then
  echo "[pre-push] canonical lint not found at $LINT" >&2
  echo "[pre-push] pull KTPInfrastructure (sibling dir) to latest, or bypass with --no-verify" >&2
  exit 1
fi

if ! "$LINT"; then
  exit 1
fi
```

The KTPInfrastructure-as-sibling-dir convention is already enforced by
`KTPAMXX/scripts/pre-push.sh` and `DoD-hud-observer/scripts/pre-push.sh` —
this re-uses the same constraint.

## Adding a new shared hook

1. Drop the script in this directory with a self-contained header documenting
   what it catches and why
2. Update the table above
3. Open a follow-up PR against each consumer to wire it into their
   `scripts/pre-push.sh`
