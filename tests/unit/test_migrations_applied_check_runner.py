"""scripts/ktp-migrations-applied-check.sh: exit codes pass through, the stamp means a verdict.

The runner drives KTPAntiCheat's checker, which this repo cannot carry, so a stand-in
checker exposes the same two things the runner relies on: a module-level SNAPSHOT_SQL
with a {db} placeholder, and the 0/1/2 exit contract. git is real (a scratch origin and
a clone of it); mysql is a stub on PATH that records the SQL it was handed.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

RUNNER = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-migrations-applied-check.sh"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(
    shutil.which(BASH) is None or shutil.which("git") is None or shutil.which("python3") is None,
    reason="needs bash, git and python3",
)

FAKE_CHECKER = '''import os, sys
DB = os.environ.get("KTP_AC_DB", "hlstatsx")
SNAPSHOT_SQL = "SELECT 'probe-{db}';"
if __name__ == "__main__":
    snap = sys.argv[sys.argv.index("--snapshot") + 1]
    assert open(snap).read() == "schema-from-stub\\n", "the runner did not pass the mysql output"
    print("fake checker ran")
    sys.exit(int(os.environ.get("FAKE_RC", "0")))
'''


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def env(tmp_path):
    origin = tmp_path / "origin"
    (origin / "scripts").mkdir(parents=True)
    (origin / "docs").mkdir()
    (origin / "sql" / "migrations").mkdir(parents=True)
    (origin / "scripts" / "check-migrations-applied.py").write_text(FAKE_CHECKER)
    (origin / "docs" / "MIGRATIONS_APPLIED.md").write_text("ledger\n")
    (origin / "sql" / "migrations" / "001.sql").write_text("SELECT 1;\n")
    git(origin, "init", "-q", "-b", "main")
    git(origin, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(origin, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed")
    checkout = tmp_path / "state" / "KTPAntiCheat"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)

    stubs = tmp_path / "bin"
    stubs.mkdir()
    mysql = stubs / "mysql"
    mysql.write_text(
        '#!/bin/bash\ncat > "$MYSQL_STDIN_LOG"\n'
        '[ -n "${MYSQL_FAIL:-}" ] && exit 1\necho schema-from-stub\n'
    )
    mysql.chmod(0o755)

    e = dict(os.environ,
             PATH="%s%s%s" % (stubs, os.pathsep, os.environ["PATH"]),
             STATE_DIRECTORY=str(tmp_path / "state"),
             MYSQL_STDIN_LOG=str(tmp_path / "mysql-stdin.txt"),
             KTP_AC_DB="hlstatsx")
    head = subprocess.run(["git", "-C", str(origin), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    return {"env": e, "tmp": tmp_path, "origin": origin, "head": head,
            "stamp": tmp_path / "state" / "last-checked"}


def run(ctx, **extra):
    e = dict(ctx["env"], **extra)
    return subprocess.run([BASH, str(RUNNER)], capture_output=True, text=True, env=e)


def test_a_clean_check_exits_0_and_stamps_the_commit_it_read(env):
    p = run(env, FAKE_RC="0")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "fake checker ran" in p.stdout
    stamp = env["stamp"].read_text()
    assert "commit=%s" % env["head"] in stamp
    assert "rc=0" in stamp


def test_the_snapshot_query_comes_from_the_checker_itself(env):
    run(env, FAKE_RC="0")
    assert (env["tmp"] / "mysql-stdin.txt").read_text().strip() == "SELECT 'probe-hlstatsx';"


def test_a_finding_exits_1_and_still_stamps(env):
    """A finding is a completed check; the unit fails on it and OnFailure posts it."""
    p = run(env, FAKE_RC="1")
    assert p.returncode == 1
    assert "rc=1" in env["stamp"].read_text()


def test_a_could_not_check_exits_2_and_writes_no_stamp(env):
    p = run(env, FAKE_RC="2")
    assert p.returncode == 2
    assert not env["stamp"].exists()


def test_a_failed_fetch_is_could_not_check_never_a_stale_run(env):
    shutil.rmtree(env["origin"])
    p = run(env, FAKE_RC="0")
    assert p.returncode == 2
    assert "git fetch failed" in p.stderr
    assert "fake checker ran" not in p.stdout
    assert not env["stamp"].exists()


def test_a_failed_schema_read_is_could_not_check(env):
    p = run(env, FAKE_RC="0", MYSQL_FAIL="1")
    assert p.returncode == 2
    assert "fake checker ran" not in p.stdout
    assert not env["stamp"].exists()


def test_no_state_directory_and_no_overrides_refuses(env):
    e = {k: v for k, v in env["env"].items() if k != "STATE_DIRECTORY"}
    p = subprocess.run([BASH, str(RUNNER)], capture_output=True, text=True, env=e)
    assert p.returncode == 2
    assert "CANNOT CHECK" in p.stderr
