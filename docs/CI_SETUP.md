# KTP CI Setup Checklist

One-time GitHub configuration steps for the Tier 1 smoke + config-test
workflows shipped 2026-04-26 → 2026-04-27. Most of this is operator
work that requires clicking through the GitHub UI; not automatable from
within the workflows themselves.

If you're standing up CI for a NEW KTP repo, work top to bottom. If you're
auditing an EXISTING repo, the [verification checklist](#verification-checklist)
at the bottom is faster.

---

## 1. Org-level: reusable workflow access policy

The smoke workflow at `KTPInfrastructure/.github/workflows/smoke-callable.yml`
is invoked by per-project repos via `workflow_call`. GitHub blocks cross-repo
reusable-workflow calls by default unless the org permits it.

**Do once, per organization:**

1. Go to **Org settings → Actions → General**
2. Under **Access policy for actions and reusable workflows**, set:
   - "Accessible from repositories in the organization" — preferred for KTP
   - OR "Public" if all KTP repos are public

If this isn't set, callers will fail with `repository not accessible`
on the first reusable-workflow call.

---

## 2. Org-level: cross-repo checkout secret

The smoke workflow checks out 14 sibling KTP repos (the change under test +
13 dependencies). `${{ github.token }}` only reaches the workflow's own repo,
so it can't clone any other private KTP repo. A Personal Access Token (PAT)
with read access on every KTP repo is required.

**Do once, per organization:**

1. Create a PAT (classic, NOT fine-grained — workflow_call doesn't pass
   fine-grained tokens cleanly):
   - User settings → Developer settings → Personal access tokens → Tokens (classic)
   - Scope: `repo` (read access — full control of private repos is the only level
     classic PATs offer; treat the secret accordingly)
   - Expiration: 1 year (set a calendar reminder to rotate)
2. Save as an **organization secret**:
   - Org settings → Secrets and variables → Actions → New organization secret
   - Name: `KTP_CHECKOUT_TOKEN`
   - Value: the PAT
   - Repository access: "Selected repositories" → all KTP repos that ship
     a smoke workflow (9 caller repos as of 2026-04-28 — every KTP plugin
     repo plus KTPAmxxCurl; add as we go)

If you'd rather scope per-repo: copy the PAT into each KTP repo's
"Repository secrets" instead, with the same name. Org-level is preferred —
one place to rotate.

If the secret is missing, the smoke workflow falls back to `${{ github.token }}`
and will fail to clone the first private sibling. Error looks like:
`fatal: could not read Username for 'https://github.com/...'`.

---

## 3. Per-repo: branch protection

Per the [TEST_INFRASTRUCTURE_PLAN.md](../TEST_INFRASTRUCTURE_PLAN.md) decision
(Q2, locked 2026-04-24): Tier 1 status checks block merges from day one.
Tier 2 starts warn-only (because flaky-by-default initially) and flips to
blocking after 2 weeks of green-on-main.

**Do once per smoke-equipped KTP repo** (all 9 smoke callers as of
2026-04-28; KTPScoreTracker/KTPFileChecker/KTPAntiCheat remain blocked —
see the root TODO "Branch protection" entry):

1. **Repo settings → Branches → Branch protection rules**
2. Add rule for `main` (or `master`):
   - ✅ Require a pull request before merging — 1 review
   - ✅ Require status checks to pass before merging
     - ✅ Require branches to be up to date before merging
     - **Required status checks:**
       - `smoke / smoke` (from the per-project caller workflow)
       - `Tier 1 Config Tests / config-tests` (only on KTPInfrastructure —
         the workflow lives there and only fires when configs change)
   - ✅ Do not allow bypassing the above settings (admins can override per-PR
     if labelled, but the default is to enforce — see hotfix path below)

The status check name is what GitHub reports back to the PR — usually
`<workflow-name> / <job-name>`. After the first run, the dropdown will
populate with the available checks; pick the smoke one.

### Hotfix bypass

For emergency production fixes that can't wait for CI:

1. Open the PR
2. As a repo admin, "Merge without waiting for status checks to pass"
3. Document the bypass reason in the PR body (`HOTFIX: <one-line rationale>`)
4. File a follow-up issue to add a regression test for whatever broke

The bypass is logged in PR history; rare-use convention is the only thing
keeping it from becoming a hole. Audit usage quarterly.

---

## 4. Per-repo: workflow files

For a NEW KTP repo getting Tier 1 smoke for the first time:

1. Copy `.github/workflows/smoke.yml` from `KTPAmxxCurl` (for C++ modules) or
   `KTPMatchHandler` (for AMX plugins). Both are 35-line callers.
2. Adjust the `with:` block:
   - `under_test_label: NewRepoName`
   - `assert_module: <module-name>` for module repos (e.g. `dodx`, `reapi`)
   - `assert_plugin: <plugin-name>` for plugin repos (e.g. `KTPCvarChecker`)
3. Push, watch the first run on the Actions tab. Adjust if anything red.
4. Once green, add the status check to branch protection (step 3 above).

See [`tests/smoke/README.md`](../tests/smoke/README.md) for the harness
internals and the truncation-aware matching for AMXX's 11-char filename clip.

---

## 5. Deploy scripts: pre-flight integration

`KTPInfrastructure/scripts/preflight.py` is a library + CLI that asserts
CI is green for HEAD before letting a deploy proceed. Add it to deploy
scripts to prevent deploying broken code that nobody noticed CI flagged.

### Library integration (preferred for Python deploy scripts)

```python
# At the top of any deploy script
import sys
sys.path.insert(0, '/path/to/KTPInfrastructure/scripts')
from preflight import assert_ci_passing, PreflightError

force = '--force-deploy' in sys.argv
try:
    assert_ci_passing(repo_root='.', force=force)
except PreflightError as e:
    print(f"REFUSING TO DEPLOY: {e}", file=sys.stderr)
    sys.exit(1)

# ...rest of deploy logic
```

### Shell integration (for bash deploy scripts)

```bash
python -m preflight check --repo-root . || { echo "REFUSING TO DEPLOY"; exit 1; }
```

### Requirements

- `gh` CLI installed and authenticated (`gh auth login`) on the dev machine
- Or `GITHUB_TOKEN` / `GH_TOKEN` env var if running headless
- The current commit must have been pushed to GitHub (else there are no
  workflow runs to query)

### Force-deploy escape hatch

```python
assert_ci_passing(force=True)        # library
python -m preflight check --force    # CLI
```

Use sparingly. A printed warning goes to stderr, but the deploy proceeds.
Same convention as the branch-protection bypass: log the reason, file a
follow-up to fix CI.

---

## 6. GHCR base image (fast-path optimization)

Shipped 2026-04-27 as the runtime-side optimization. Reduces per-smoke-run
time from ~12-20 min (full stack rebuild) to ~3-5 min (pull base + build
under-test only). Per-project callers opt in via `use_base_image: true`
(default).

### One-time setup

1. **Confirm package permissions on the org/account.**
   - Org settings → Member privileges → Package creation: enable for `Public`
     and/or `Private`. KTP defaults to private packages.
2. **First publish.**
   - Manually trigger `Publish runtime test-base image` workflow in
     KTPInfrastructure: Actions tab → workflow → Run workflow.
   - First run takes ~15-20 min (the full stack build it's replacing). Once
     it completes, `ghcr.io/<owner>/ktp-runtime-test-base:latest` exists.
3. **Set package visibility** (only if needed).
   - GitHub → your packages → `ktp-runtime-test-base` → Package settings →
     Change visibility. Default is private; smoke runs in private repos can
     pull private packages with `${{ secrets.GITHUB_TOKEN }}` automatically
     (the `packages: read` permission in the smoke workflow grants this).
   - If KTP repos are mixed public/private and any public repo's smoke
     needs the base, make the package public OR push a public copy.
4. **Verify a smoke run uses the base.**
   - Push any change to KTPMatchHandler (or KTPAmxxCurl). Watch the smoke
     run in Actions. The "Pull base image" step should fire and complete in
     ~30s; "Compile AMX plugin against base image" / "Build C++ module"
     replaces the long "Build all KTP components" step.

### Maintenance

- **Nightly rebuild** (cron 04:30 UTC) is automatic. Failures post to
  the workflow's run history; consider wiring a Discord alert via the
  same `relay_url` mechanism already used by the fleet drift audit.
- **Manual rebuild** when a base component (KTPReHLDS, KTPAMXX, etc.)
  lands a critical change that smoke needs to pick up immediately —
  Actions tab → "Publish runtime test-base image" → Run workflow.
- **Package size** is ~2 GB per tag. The publish workflow tags `:latest`
  + the KTPInfrastructure short SHA. Old SHA tags accumulate. Periodic
  cleanup recommended:
  - GitHub → packages → `ktp-runtime-test-base` → manually delete
    older versions
  - OR add a cleanup step using `actions/delete-package-versions` to
    publish-base-image.yml that retains the last N versions
- **Storage cost**: GHCR offers 500 MB free for private packages; KTP's
  size will exceed that. Storage at $0.25/GB/mo means ~$0.50/mo per tag.
  Keep ~10 tagged versions = ~$5/mo, negligible.

### Fallback / disabling

Per-caller `use_base_image: false` reverts to the slow path (full stack
rebuild) without code changes. Use when:
- Base image is broken (rebuild failed; hasn't run yet)
- Testing a change to the build infrastructure itself (Makefile,
  build/Dockerfile, runtime/Dockerfile) — fast path can't see those
  changes since it pulls the pre-built base
- Debugging a smoke discrepancy ("does the slow path still pass?")

The publish-base-image.yml workflow itself uses the slow path
implicitly (it's what builds the base in the first place; no chicken
to call). It's not a `workflow_call` consumer of smoke-callable.yml.

## 7. KTP_CHECKOUT_TOKEN rotation

Set a calendar reminder for the PAT expiration date (1 year by default).
When rotating:

1. Generate new PAT with same scopes
2. Update `KTP_CHECKOUT_TOKEN` org secret to the new PAT
3. Run any one smoke workflow manually (`workflow_dispatch`) to confirm
   the new token works
4. Revoke the old PAT

If the PAT expires unnoticed, every smoke run goes red on the first
sibling-checkout step. The error is loud and immediate.

---

## Verification checklist

For each KTP repo with a smoke workflow:

- [ ] `.github/workflows/smoke.yml` present and parses (`yamllint`, `python -c "import yaml; yaml.safe_load(open(...))"`)
- [ ] Workflow uses `${{ secrets.KTP_CHECKOUT_TOKEN }}` (not a hardcoded token)
- [ ] One green workflow run on `main` since the smoke was added
- [ ] Branch protection rule on `main` includes `smoke / smoke` as required check
- [ ] At least one PR has been merged through the gate (proves the path works)

Org-level:

- [ ] Reusable workflow access policy permits cross-repo calls
- [ ] `KTP_CHECKOUT_TOKEN` org secret exists and is shared with smoke repos
- [ ] PAT expiration on a calendar
