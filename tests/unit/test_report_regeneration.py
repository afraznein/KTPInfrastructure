"""The gated report-regeneration workflow and the scripts it runs on the box.

The workflow runs as root on the production data server, so its guards are the
contract: the approval environment, dry_run on by default, no code-triggered
events, its own concurrency group, a checkout that must be clean reviewed main,
and a public summary that carries counts and nothing a report names.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import report_regen_guard as guard  # noqa: E402
from scripts import report_regen_summary as summary  # noqa: E402

WORKFLOW = ROOT / ".github/workflows/report-regeneration.yml"
WORKFLOWS = ROOT / ".github/workflows"


def _wf() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _input_block(name: str) -> str:
    m = re.search(rf"^      {name}:\n((?:        .*\n)+)", _wf(), re.MULTILINE)
    assert m, f"input {name} not declared"
    return m.group(1)


# ── the workflow file ──────────────────────────────────────────────────────

def test_job_is_held_by_the_operator_environment():
    assert re.search(r"^    environment: report-regeneration$", _wf(), re.MULTILINE)


def test_workflow_never_creates_or_edits_environments():
    wf = _wf()
    assert "/environments" not in wf
    assert "gh api" not in wf


def test_dry_run_defaults_true():
    block = _input_block("dry_run")
    assert "type: boolean" in block
    assert "default: true" in block


def test_reason_is_required_and_scope_mirrors_report_service():
    assert "required: true" in _input_block("reason")
    scope = _input_block("scope")
    assert "options: [pending, match_ids]" in scope
    assert "default: pending" in scope
    assert tuple(guard.SCOPES) == ("pending", "match_ids")


def test_only_manual_dispatch_triggers_it():
    on = re.search(r"^on:\n((?:  .*\n|\n)+?)^\S", _wf(), re.MULTILINE).group(1)
    triggers = re.findall(r"^  (\w+):", on, re.MULTILINE)
    assert triggers == ["workflow_dispatch"]
    assert "github.ref == 'refs/heads/main'" in _wf()


def test_runs_on_the_tier2_runner_against_the_reports_checkout():
    wf = _wf()
    assert "runs-on: [self-hosted, ktp-tier2]" in wf
    assert "REPORTS_REPO: /opt/ktp-reports/KTPInfrastructure" in wf
    assert "REPORTS_USER: ktpreports" in wf
    assert "/opt/ktp-infra" not in wf


def test_concurrency_group_is_its_own():
    group = re.search(r"^concurrency:\n(?:  #.*\n)*  group: (\S+)", _wf(), re.MULTILINE).group(1)
    assert group == "report-regeneration"
    assert "cancel-in-progress: false" in _wf()
    for other in WORKFLOWS.glob("*.yml"):
        if other == WORKFLOW:
            continue
        for g in re.findall(r"group: (\S+)", other.read_text(encoding="utf-8")):
            assert not g.startswith("report-regeneration"), other.name


def test_checkout_guard_runs_before_any_pipeline_step():
    wf = _wf()
    guard_at = wf.index("report_regen_guard.py checkout")
    for step in ("scripts.report_service", "scripts.report_sync",
                 "systemctl start ktp-reports.service"):
        assert wf.index(step) > guard_at, step
    assert '--expect-sha "$GITHUB_SHA"' in wf


def test_workflow_never_moves_the_checkout():
    wf = _wf()
    for verb in ("git pull", "git merge", "git checkout", "git reset", "git fetch"):
        assert verb not in wf, verb


def test_real_run_steps_are_gated_off_dry_run():
    wf = _wf()
    for name in ("Regenerate the named matches",
                 "Run the report service (generate pending, aggregate, sync, site refresh)"):
        step = wf[wf.index(f"- name: {name}"):]
        assert "!inputs.dry_run" in step.split("run: |", 1)[0], name
    dry = wf[wf.index("- name: Dry run"):wf.index("- name: Regenerate the named")]
    assert "if: inputs.dry_run" in dry
    assert dry.count("--dry-run") == 3
    assert "systemctl start" not in dry


def test_inputs_reach_shell_only_through_env():
    run_bodies = re.findall(r"run: \|\n((?:          .*\n|\n)+)", _wf())
    for body in run_bodies:
        assert "${{" not in body


def test_pipeline_output_is_kept_off_the_public_log():
    lines = _wf().splitlines()
    invocations = [ln for ln in lines
                   if re.search(r"--repo \. generate|scripts\.report_sync --since", ln)]
    assert len(invocations) == 4
    for ln in invocations:
        assert re.search(r'>> "\$(seg|RUNNER_TEMP/segment\.log)" 2>&1$', ln), ln
    assert "report_regen_summary.py" in _wf()


# ── inputs ─────────────────────────────────────────────────────────────────

def test_inputs_pending_ok():
    assert guard.validate_inputs("pending", "", "schema bump to v26") == []


@pytest.mark.parametrize("scope,ids,reason", [
    ("all", "", "r"),
    ("pending", "", "   "),
    ("pending", "1790186507-NY1", "r"),
    ("match_ids", "", "r"),
    ("match_ids", "abc; rm -rf /", "r"),
    ("match_ids", "$(id)", "r"),
    ("match_ids", " ".join(f"m{i}" for i in range(guard.MAX_MATCH_IDS + 1)), "r"),
    ("pending", "", "x" * (guard.MAX_REASON + 1)),
])
def test_inputs_refused(scope, ids, reason):
    with pytest.raises(guard.Refused):
        guard.validate_inputs(scope, ids, reason)


def test_match_ids_split_and_dedup():
    assert guard.validate_inputs("match_ids", "a-1, b.2\n a-1", "r") == ["a-1", "b.2"]


# ── floor and window ───────────────────────────────────────────────────────

UNIT = """# /etc/systemd/system/ktp-reports.service
[Service]
# generate's --since 1999-01-01 only scopes discovery
ExecStart=/usr/bin/python3 -m scripts.report_service --repo . generate --since 2026-09-13
ExecStart=/usr/bin/python3 -m scripts.report_service --repo . aggregate --since 2026-09-13
"""


def test_floor_reads_execstart_not_comments():
    assert guard.unit_floor(UNIT) == "2026-09-13"


def test_floor_takes_the_drop_in_override():
    drop_in = UNIT + ("\n# /etc/systemd/system/ktp-reports.service.d/s11.conf\n"
                      "[Service]\nExecStart=\nExecStart=/usr/bin/python3 -m "
                      "scripts.report_service --repo . generate --since 2027-01-10\n")
    assert guard.unit_floor(drop_in) == "2027-01-10"


def test_floor_missing_refuses():
    with pytest.raises(guard.Refused):
        guard.unit_floor("[Service]\nExecStart=/bin/true\n")


def test_floor_matches_the_repo_unit():
    unit = (ROOT / "systemd/ktp-reports.service").read_text(encoding="utf-8")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", guard.unit_floor(unit))


def test_window():
    assert guard.check_window(1000, 2000, 480) == 1000
    with pytest.raises(guard.Refused):
        guard.check_window(1000, 1400, 480)
    with pytest.raises(guard.Refused):
        guard.check_window(1000, 0, 480)


# ── the checkout guard, against real git ───────────────────────────────────

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


def commit(work: Path, text: str) -> str:
    (work / "f.txt").write_text(text)
    git(work, "add", "f.txt")
    git(work, "commit", "-q", "-m", text)
    git(work, "push", "-q", "origin", "HEAD:main")
    return git(work, "rev-parse", "HEAD")


@pytest.fixture
def estate(tmp_path: Path):
    upstream = tmp_path / "up.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(upstream))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(upstream), str(seed))
    a = commit(seed, "v1")
    serving = tmp_path / "serving"
    git(tmp_path, "clone", "-q", str(upstream), str(serving))
    return {"seed": seed, "serving": serving, "a": a}


@needs_git
def test_clean_checkout_at_main_passes(estate):
    assert guard.check_checkout(estate["serving"], estate["a"]) == estate["a"]


@needs_git
def test_dirty_checkout_refused(estate):
    (estate["serving"] / "f.txt").write_text("hand edit\n")
    with pytest.raises(guard.Refused, match="dirty"):
        guard.check_checkout(estate["serving"], estate["a"])


@needs_git
def test_untracked_file_refused(estate):
    (estate["serving"] / "stray.py").write_text("x\n")
    with pytest.raises(guard.Refused, match="dirty"):
        guard.check_checkout(estate["serving"], estate["a"])


@needs_git
def test_behind_checkout_refused_and_not_moved(estate):
    b = commit(estate["seed"], "v2")
    with pytest.raises(guard.Refused, match="is not fetched origin/main"):
        guard.check_checkout(estate["serving"], b)
    serving = estate["serving"]
    assert git(serving, "rev-parse", "HEAD") == estate["a"]
    assert git(serving, "rev-parse", "refs/heads/main") == estate["a"]
    # The fetch did happen: the comparison was against the new main.
    assert git(serving, "rev-parse", "refs/remotes/origin/main") == b
    assert (serving / "f.txt").read_text() == "v1"


@needs_git
def test_stale_tracking_ref_is_refreshed_before_comparing(estate):
    # Without the fetch, HEAD == the stale origin/main and a behind tree passes.
    b = commit(estate["seed"], "v2")
    with pytest.raises(guard.Refused):
        guard.check_checkout(estate["serving"], estate["a"])
    assert b


@needs_git
def test_heads_refspec_config_does_not_move_local_main(estate):
    serving = estate["serving"]
    git(serving, "config", "--add", "remote.origin.fetch", "+refs/heads/*:refs/heads/*")
    git(serving, "checkout", "-q", "--detach")
    commit(estate["seed"], "v2")
    with pytest.raises(guard.Refused):
        guard.check_checkout(serving, estate["a"])
    assert git(serving, "rev-parse", "refs/heads/main") == estate["a"]


@needs_git
def test_dispatched_commit_must_be_main(estate):
    with pytest.raises(guard.Refused, match="dispatched commit"):
        guard.check_checkout(estate["serving"], "f" * 40)
    with pytest.raises(guard.Refused):
        guard.check_checkout(estate["serving"], "main")


@needs_git
def test_cli_exit_codes(estate, tmp_path):
    ok = guard.main(["checkout", "--repo", str(estate["serving"]), "--expect-sha", estate["a"]])
    assert ok == 0
    (estate["serving"] / "f.txt").write_text("hand edit\n")
    assert guard.main(["checkout", "--repo", str(estate["serving"]), "--expect-sha", estate["a"]]) == 1
    assert guard.main(["checkout", "--repo", str(tmp_path / "nope"), "--expect-sha", estate["a"]]) == 2


# ── the public summary ─────────────────────────────────────────────────────

LOG = """accumulation scorer: available
pending: 3 matches (schema v25)
match types built: 0, 4 official + 2 shadow (built for analytics, held back by aggregate and report_sync)
WARNING: 1790186507-NY1 is not an official match type: persisted anyway, but aggregate and report_sync hold its report back
excluded by match_type filter: 2 (12man 1, scrim 1)
  1790000001-ATL1: persisted, publishable=True
  1790000002-DAL2: persisted, publishable=False
  1790000003-NY3: FAILED KeyError: 'PlayerNameSecret'
mysql calls: 40; failures: 1
  map_profiles: wrote revision 12 (hash abc)
  ktpr_v22: unchanged (revision 7)
reports to sync: 2
website aliases: 140 steam ids
  1790000001-ATL1: name shared by two players, left as played: SomePlayer
  synced 1790000001-ATL1 v25 r2
  synced aggregate map_profiles r12
site revalidate: scope=ktp ok (200)
done: 1 reports, 1 aggregates
"""


def test_summary_counts():
    c = summary.summarize(LOG)
    assert c["pending matches"] == 3
    assert c["reports persisted, publishable"] == 1
    assert c["reports persisted, held (not publishable)"] == 1
    assert c["report builds FAILED"] == 1
    assert c["out-of-scope explicit ids (held back)"] == 1
    assert c["excluded by match_type"] == 2
    assert c["aggregates rewritten"] == 1
    assert c["aggregates unchanged"] == 1
    assert c["reports to sync"] == 2
    assert c["reports synced"] == 1
    assert c["aggregates synced"] == 1
    assert c["site cache refresh"] == "refreshed"


def test_summary_dry_run_counts():
    c = summary.summarize("pending: 4 matches (schema v25)\n"
                          "dry run: would build 4 reports; nothing persisted\n"
                          "reports to sync: 1\n  DRY 179-ATL1 v25 r1\n"
                          "  DRY aggregate map_profiles r3\n")
    assert c["would build (dry run)"] == 4
    assert c["reports that would sync (dry run)"] == 1
    assert c["aggregates that would sync (dry run)"] == 1
    assert "reports synced" not in c


def test_summary_never_echoes_input():
    out = summary.render("real run (pending)", summary.summarize(LOG))
    for leak in ("1790", "SomePlayer", "PlayerNameSecret", "ATL1", "NY1", "steam"):
        assert leak not in out, leak
    assert re.search(r"STEAM_\d", out) is None


def test_summary_empty_input_says_so():
    assert "no pipeline output recognised" in summary.render("dry run", {})


# ── generate --dry-run persists nothing ────────────────────────────────────

class _Db:
    def __init__(self):
        self.calls = 0
        self.queries = []

    def sql(self, query):
        self.calls += 1
        self.queries.append(query)
        if "COUNT(DISTINCT" in query:
            return "mt\tn\n"
        return "match_id\nm-1\nm-2\n"


class _Ma:
    SCHEMA_VERSION = 25

    def source_capabilities(self, db):
        raise AssertionError("a dry run must not probe sources")

    def build_report(self, *a, **k):
        raise AssertionError("a dry run must not build a report")


def _generate(argv, capsys, monkeypatch):
    from scripts import report_service
    db = _Db()
    monkeypatch.setattr(report_service, "LocalMysql", lambda: db)
    monkeypatch.setattr(report_service, "load_match_analytics", lambda repo: _Ma())
    rc = report_service.main(["--repo", ".", "generate", *argv])
    return rc, db, capsys.readouterr().out


def test_generate_dry_run_counts_and_writes_nothing(capsys, monkeypatch):
    rc, db, out = _generate(["--dry-run", "--since", "2026-09-13"], capsys, monkeypatch)
    assert rc == 0
    assert "pending: 2 matches" in out
    assert "dry run: would build 2 reports; nothing persisted" in out
    assert not any("INSERT" in q.upper() for q in db.queries)
    assert summary.summarize(out)["would build (dry run)"] == 2


def test_generate_without_dry_run_still_builds(capsys, monkeypatch):
    with pytest.raises(AssertionError, match="probe sources"):
        _generate(["--since", "2026-09-13"], capsys, monkeypatch)
