"""ktp-install: installs a git blob byte-for-byte and records it in the deploy manifest.

Every verdict is exercised in both directions -- a report that cannot say DRIFT
proves nothing, and neither does an install that cannot refuse.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(_ROOT, "scripts", "ktp-install")
HEADER = "\t".join(["installed_path", "md5", "source_repo", "source_commit", "source_path",
                    "deployed_at_iso", "previous_md5", "deployed_by"])

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses fcntl and POSIX modes")


def md5(b):
    return hashlib.md5(b).hexdigest()


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


V1 = b"#!/bin/bash\necho v1\n"
V2 = b"#!/bin/bash\necho v2\n"


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "tool.sh").write_bytes(V1)
    (repo / "scripts" / "conf.sh.example").write_bytes(b"SECRET=\"YOUR_SECRET_HERE\"\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "v1")
    c1 = git(repo, "rev-parse", "HEAD")
    (repo / "scripts" / "tool.sh").write_bytes(V2)
    git(repo, "commit", "-q", "-am", "v2")
    c2 = git(repo, "rev-parse", "HEAD")
    dest = tmp_path / "bin"
    dest.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    e = dict(os.environ, KTP_MANIFEST=str(tmp_path / "share" / "DEPLOYED.tsv"),
             KTP_INSTALL_BACKUPS=str(tmp_path / "backups"), KTP_DEPLOYED_BY="test@host", HOME=str(home))
    return dict(repo=repo, c1=c1, c2=c2, dest=dest, env=e, tmp=tmp_path, home=home,
                manifest=tmp_path / "share" / "DEPLOYED.tsv")


def run(env, *args, extra_env=None):
    e = dict(env["env"], **(extra_env or {}))
    return subprocess.run([sys.executable, TOOL, *args], env=e, capture_output=True, text=True)


def install(env, commit, expect, *extra, dest_name="tool.sh", src="scripts/tool.sh"):
    return run(env, "--repo", str(env["repo"]), "--commit", commit, "--src", src,
               "--dest", str(env["dest"] / dest_name), "--expect-md5", expect, *extra)


def after_baseline(p):
    """Stdout with the --against-ref baseline line removed.

    The baseline is a header, not a row: it says what a CURRENT below is current
    WITH, which is the whole point of having it. Tests assert on the rows.
    """
    lines = p.stdout.splitlines(keepends=True)
    if lines and lines[0].startswith("baseline "):
        lines = lines[1:]
    return "".join(lines)


def rows(env, path=None):
    lines = (path or env["manifest"]).read_text().splitlines()
    assert lines[0] == HEADER
    return [l.split("\t") for l in lines[1:]]


def test_fresh_install_is_the_blob_and_is_recorded(env):
    p = install(env, env["c1"], "-")
    assert p.returncode == 0, p.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V1
    r = rows(env)
    assert len(r) == 1
    assert r[0][0] == str(env["dest"] / "tool.sh")
    assert r[0][1] == md5(V1)
    assert r[0][3] == env["c1"] and len(r[0][3]) == 40
    assert r[0][4] == "scripts/tool.sh"
    assert r[0][6] == "-" and r[0][7] == "test@host"
    assert os.stat(env["dest"] / "tool.sh").st_mode & 0o777 == 0o755


def test_upgrade_banks_backup_keeps_mode_and_records_previous_md5(env):
    install(env, env["c1"], "-")
    os.chmod(env["dest"] / "tool.sh", 0o750)
    p = install(env, env["c2"], md5(V1))
    assert p.returncode == 0, p.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V2
    assert os.stat(env["dest"] / "tool.sh").st_mode & 0o777 == 0o750
    r = rows(env)
    assert [x[3] for x in r] == [env["c1"], env["c2"]]
    assert r[1][6] == md5(V1)
    backups = os.listdir(env["tmp"] / "backups")
    assert len(backups) == 1 and md5(V1)[:8] in backups[0]
    assert md5((env["tmp"] / "backups" / backups[0]).read_bytes()) == md5(V1)
    assert not (env["dest"] / "tool.sh.new").exists()


def _foreign_ownership():
    """An (uid, gid) this process does not already have but is allowed to set, or None.

    Unprivileged that means a supplementary group, since chgrp to one needs no privilege;
    as root it means any other account. Either is enough, because the defect is that the
    swap's new inode lands on the INSTALLER's ids, so the assertion fails for the same
    reason whichever leg supplies them.
    """
    if os.geteuid() == 0:
        import pwd

        for p in pwd.getpwall():
            if p.pw_uid not in (0, os.geteuid()) and p.pw_gid not in (0, os.getegid()):
                return p.pw_uid, p.pw_gid
        return None
    others = [g for g in os.getgroups() if g != os.getegid()]
    return (os.geteuid(), others[0]) if others else None


def test_upgrade_preserves_the_files_own_owner_not_the_installers(env):
    want = _foreign_ownership()
    if want is None:
        pytest.skip("no uid/gid this process may set that it does not already have")
    assert want != (os.geteuid(), os.getegid()), "control: the install must have to restore these"
    install(env, env["c1"], "-")
    dest = env["dest"] / "tool.sh"
    os.chown(dest, want[0], want[1])
    os.chmod(dest, 0o750)
    p = install(env, env["c2"], md5(V1))
    assert p.returncode == 0, p.stderr
    st = os.stat(dest)
    assert (st.st_uid, st.st_gid) == want
    assert st.st_mode & 0o777 == 0o750


def test_a_fresh_install_has_no_prior_owner_to_preserve(env):
    """Regression guard, not evidence: the preserve step must not fire with nothing to carry."""
    p = install(env, env["c1"], "-")
    assert p.returncode == 0, p.stderr
    st = os.stat(env["dest"] / "tool.sh")
    assert (st.st_uid, st.st_gid) == (os.geteuid(), os.getegid())


def test_wrong_expected_md5_refuses_and_changes_nothing(env):
    install(env, env["c1"], "-")
    p = install(env, env["c2"], "0" * 32)
    assert p.returncode != 0 and "not touching it" in p.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V1
    assert len(rows(env)) == 1


def test_expecting_absent_refuses_when_file_exists(env):
    (env["dest"] / "tool.sh").write_bytes(b"hand edited\n")
    p = install(env, env["c1"], "-")
    assert p.returncode != 0
    assert (env["dest"] / "tool.sh").read_bytes() == b"hand edited\n"
    assert not env["manifest"].exists()


def test_same_bytes_is_not_a_new_install(env):
    install(env, env["c1"], "-")
    p = install(env, env["c1"], md5(V1))
    assert p.returncode != 0 and "nothing to install" in p.stderr
    assert len(rows(env)) == 1


def test_repo_mode_file_must_equal_blob(env):
    other = env["tmp"] / "other.sh"
    other.write_bytes(b"#!/bin/bash\necho tampered\n")
    p = install(env, env["c2"], "-", "--file", str(other))
    assert p.returncode != 0 and "differs" in p.stderr
    assert not (env["dest"] / "tool.sh").exists()


def test_no_repo_mode_needs_blob_md5_and_checks_it(env):
    pushed = env["tmp"] / "pushed.sh"
    pushed.write_bytes(V2)
    base = ["--file", str(pushed), "--source-repo", "KTPInfrastructure", "--commit", env["c2"],
            "--src", "scripts/tool.sh", "--dest", str(env["dest"] / "tool.sh"), "--expect-md5", "-"]
    p = run(env, *base)
    assert p.returncode != 0 and "--blob-md5" in p.stderr
    p = run(env, *base, "--blob-md5", md5(V1))
    assert p.returncode != 0 and "not the blob" in p.stderr
    assert not (env["dest"] / "tool.sh").exists()
    p = run(env, *base, "--blob-md5", md5(V2))
    assert p.returncode == 0, p.stderr
    r = rows(env)[-1]
    assert r[2] == "KTPInfrastructure" and r[3] == env["c2"] and r[1] == md5(V2)


def test_no_repo_mode_refuses_a_short_sha(env):
    pushed = env["tmp"] / "pushed.sh"
    pushed.write_bytes(V2)
    p = run(env, "--file", str(pushed), "--source-repo", "X", "--commit", env["c2"][:12], "--src", "scripts/tool.sh",
            "--blob-md5", md5(V2), "--dest", str(env["dest"] / "tool.sh"), "--expect-md5", "-")
    assert p.returncode != 0 and "40-hex" in p.stderr


def test_template_records_template_source_and_filled_md5(env):
    filled = env["tmp"] / "conf.sh"
    filled.write_bytes(b"SECRET=\"real\"\n")
    p = install(env, env["c2"], "-", "--file", str(filled), "--template",
                dest_name="conf.sh", src="scripts/conf.sh.example")
    assert p.returncode == 0, p.stderr
    r = rows(env)[-1]
    assert r[1] == md5(b"SECRET=\"real\"\n")
    assert r[3] == env["c2"] and r[4] == "scripts/conf.sh.example"


def test_template_flag_and_example_source_must_agree(env):
    filled = env["tmp"] / "conf.sh"
    filled.write_bytes(b"SECRET=\"real\"\n")
    p = install(env, env["c2"], "-", "--file", str(filled), dest_name="conf.sh", src="scripts/conf.sh.example")
    assert p.returncode != 0 and "template" in p.stderr
    p = install(env, env["c2"], "-", "--file", str(filled), "--template", dest_name="conf.sh", src="scripts/tool.sh")
    assert p.returncode != 0 and ".example" in p.stderr
    assert not env["manifest"].exists()


def test_report_ok_then_drift_then_missing(env):
    install(env, env["c1"], "-")
    p = run(env, "--report")
    assert p.returncode == 0 and after_baseline(p).startswith("OK"), p.stdout
    (env["dest"] / "tool.sh").write_bytes(b"#!/bin/bash\necho hotfix\n")
    p = run(env, "--report")
    assert p.returncode == 1 and after_baseline(p).startswith("DRIFT"), p.stdout
    os.unlink(env["dest"] / "tool.sh")
    p = run(env, "--report")
    assert p.returncode == 1 and p.stdout.startswith("MISSING"), p.stdout


def test_report_labels_templated_not_drift_and_still_catches_a_changed_fill(env):
    filled = env["tmp"] / "conf.sh"
    filled.write_bytes(b"SECRET=\"real\"\n")
    install(env, env["c2"], "-", "--file", str(filled), "--template", dest_name="conf.sh", src="scripts/conf.sh.example")
    p = run(env, "--report", "--repo", str(env["repo"]))
    assert p.returncode == 0 and p.stdout.startswith("TEMPLATED"), p.stdout
    (env["dest"] / "conf.sh").write_bytes(b"SECRET=\"edited\"\n")
    p = run(env, "--report")
    assert p.returncode == 1 and after_baseline(p).startswith("DRIFT"), p.stdout


def test_report_uses_the_last_row_per_path(env):
    install(env, env["c1"], "-")
    install(env, env["c2"], md5(V1))
    p = run(env, "--report")
    assert p.returncode == 0, p.stdout
    assert env["c2"][:12] in p.stdout and env["c1"][:12] not in p.stdout


def test_report_with_repo_catches_a_row_whose_commit_does_not_hold_the_bytes(env):
    install(env, env["c1"], "-")
    env["manifest"].write_text(env["manifest"].read_text().replace(env["c1"], env["c2"]))
    assert run(env, "--report").returncode == 0
    p = run(env, "--report", "--repo", str(env["repo"]))
    assert p.returncode == 1 and "SOURCE-MISMATCH" in p.stdout, p.stdout


@pytest.mark.parametrize("content", [
    None,
    "",
    "wrong\theader\n",
    HEADER + "\n",
    HEADER + "\n/x\tshort\n",
    HEADER + "\n/x\t" + "z" * 32 + "\tR\t" + "a" * 40 + "\tp\tt\t-\tw\n",
    "\t".join(["path", "md5", "repo", "commit", "src", "at", "prev", "by"]) + "\n/x\t" + "a" * 32
    + "\tR\t" + "b" * 40 + "\tp\tt\t-\tw\n",
])
def test_report_fails_closed_on_an_untrustworthy_manifest(env, content):
    if content is not None:
        env["manifest"].parent.mkdir(parents=True, exist_ok=True)
        env["manifest"].write_text(content)
    p = run(env, "--report")
    assert p.returncode == 2 and "UNTRUSTED" in p.stdout, (p.returncode, p.stdout)


def test_install_refuses_to_append_under_a_foreign_header(env):
    env["manifest"].parent.mkdir(parents=True, exist_ok=True)
    env["manifest"].write_text("something else\n")
    p = install(env, env["c1"], "-")
    assert p.returncode != 0 and "header" in p.stderr
    assert env["manifest"].read_text() == "something else\n"


@pytest.mark.skipif(os.geteuid() == 0 if hasattr(os, "geteuid") else True, reason="needs a non-root user")
def test_non_root_default_is_the_home_manifest_and_report_reads_it(env):
    e = {"KTP_MANIFEST": "", "KTP_INSTALL_BACKUPS": ""}
    p = run(env, "--repo", str(env["repo"]), "--commit", env["c1"], "--src", "scripts/tool.sh",
            "--dest", str(env["dest"] / "tool.sh"), "--expect-md5", "-", extra_env=e)
    assert p.returncode == 0, p.stderr
    home_manifest = env["home"] / ".ktp" / "DEPLOYED.tsv"
    assert rows(env, home_manifest)[0][1] == md5(V1)
    assert not env["manifest"].exists()
    p = run(env, "--report", extra_env=e)
    assert p.returncode == 0 and after_baseline(p).startswith("OK"), p.stdout


# --- --against-ref: "untouched since install" is not "current" --------------
#
# The gap these hold open: a file nobody has edited reports OK forever while the
# repo merges past it. Both directions, on the same manifest, in one test -- a
# freshness check that cannot say CURRENT proves nothing either.


def test_report_alone_says_ok_while_against_ref_says_stale(env):
    install(env, env["c1"], "-")
    p = run(env, "--report")
    assert p.returncode == 0 and after_baseline(p).startswith("OK"), p.stdout
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", env["c2"])
    assert p.returncode == 1 and after_baseline(p).startswith("STALE"), p.stdout
    assert md5(V2)[:12] in p.stdout and env["c1"][:12] in p.stdout


def test_against_ref_says_current_when_the_installed_bytes_are_the_refs(env):
    install(env, env["c2"], "-")
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", env["c2"])
    assert p.returncode == 0 and after_baseline(p).startswith("CURRENT"), p.stdout


def test_against_ref_accepts_a_symbolic_ref(env):
    install(env, env["c1"], "-")
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 1 and after_baseline(p).startswith("STALE"), p.stdout


def test_an_unresolvable_ref_is_untrusted_not_fresh(env):
    install(env, env["c2"], "-")
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "no/such/ref")
    assert p.returncode == 2 and p.stdout.startswith("UNTRUSTED"), p.stdout


def test_against_ref_without_repo_is_untrusted(env):
    install(env, env["c2"], "-")
    p = run(env, "--report", "--against-ref", "HEAD")
    assert p.returncode == 2 and p.stdout.startswith("UNTRUSTED"), p.stdout


def test_a_source_path_the_ref_no_longer_holds_is_not_fresh(env):
    install(env, env["c2"], "-")
    git(env["repo"], "rm", "-q", "scripts/tool.sh")
    git(env["repo"], "commit", "-q", "-m", "drop it")
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 1 and after_baseline(p).startswith("SOURCE-GONE"), p.stdout


def test_a_row_from_another_repo_is_not_compared_and_does_not_fail(env):
    install(env, env["c2"], "-")
    env["manifest"].write_text(env["manifest"].read_text().replace("\trepo\t", "\tKTPElsewhere\t"))
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 0 and after_baseline(p).startswith("OTHER-REPO"), p.stdout


def test_owner_qualified_source_repo_still_compares(env):
    install(env, env["c1"], "-")
    env["manifest"].write_text(env["manifest"].read_text().replace("\trepo\t", "\tafraznein/repo\t"))
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 1 and after_baseline(p).startswith("STALE"), p.stdout


def test_freshness_never_masks_drift(env):
    install(env, env["c2"], "-")
    (env["dest"] / "tool.sh").write_bytes(b"#!/bin/bash\necho hotfix\n")
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 1 and after_baseline(p).startswith("DRIFT"), p.stdout


def test_against_ref_is_refused_on_an_install(env):
    p = install(env, env["c1"], "-", "--against-ref", "HEAD")
    assert p.returncode == 2 and "--report flag" in p.stderr, p.stderr


def test_a_recorded_commit_this_checkout_lacks_is_not_an_indictment(env, tmp_path):
    """A shallow clone cannot see old commits. Saying SOURCE-MISMATCH there turns
    'I cannot check' into 'it is wrong' -- and CI checks out shallow by default."""
    install(env, env["c2"], "-")
    env["manifest"].write_text(env["manifest"].read_text().replace(env["c2"], "b" * 40))
    p = run(env, "--report", "--repo", str(env["repo"]))
    assert p.returncode == 0 and after_baseline(p).startswith("OK"), p.stdout
    assert "not in this checkout" in p.stdout, p.stdout
    # and it still reaches a freshness verdict rather than stopping there
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 0 and after_baseline(p).startswith("CURRENT"), p.stdout


# --- --record-only: a file that is correct but unrecorded ------------------
#
# The install path refuses a no-op, so a correct-but-unrecorded file could never
# be reconciled -- --report indicted it and nothing could clear it, which is how
# a daily alert becomes a muted one. These hold the mode to the only property
# that makes it safe: it records what it checked, and refuses everything else.


def record(env, commit, *extra, dest_name="tool.sh", src="scripts/tool.sh", repo=True):
    args = ["--record-only", "--commit", commit, "--src", src, "--dest", str(env["dest"] / dest_name)]
    if repo:
        args[1:1] = ["--repo", str(env["repo"])]
    return run(env, *args, *extra)


def place(env, content, name="tool.sh"):
    (env["dest"] / name).write_bytes(content)


def test_record_only_writes_the_row_and_copies_nothing(env):
    place(env, V2)
    before = os.stat(env["dest"] / "tool.sh")
    p = record(env, env["c2"])
    assert p.returncode == 0, p.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V2
    assert os.stat(env["dest"] / "tool.sh").st_mtime_ns == before.st_mtime_ns
    assert not (env["dest"] / "tool.sh.new").exists()
    assert not (env["tmp"] / "backups").exists()
    r = rows(env)
    assert len(r) == 1
    assert r[0][0] == str(env["dest"] / "tool.sh")
    assert r[0][1] == md5(V2)
    assert r[0][3] == env["c2"] and r[0][4] == "scripts/tool.sh"
    # previous_md5 == md5 is the mark of a recorded row; an install cannot write one.
    assert r[0][6] == md5(V2)


def test_record_only_refuses_when_the_bytes_are_not_that_blob(env):
    """The one that matters. A mode that trusts its caller launders drift into a
    clean report, so this asserts the refusal, the silence of the manifest, and
    that the file was not touched on the way out."""
    place(env, V1)
    p = record(env, env["c2"])
    assert p.returncode != 0
    assert "refusing to record" in p.stderr, p.stderr
    assert md5(V1) in p.stderr and md5(V2) in p.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V1
    assert not env["manifest"].exists()


def test_record_only_then_report_says_ok_and_against_ref_says_current(env):
    place(env, V2)
    assert record(env, env["c2"]).returncode == 0
    p = run(env, "--report")
    assert p.returncode == 0 and after_baseline(p).startswith("OK"), p.stdout
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 0 and after_baseline(p).startswith("CURRENT"), p.stdout


def test_recording_an_old_commit_is_reported_stale_not_current(env):
    """Recording states which blob these bytes are, not that they are the newest.
    A record must not be able to buy CURRENT for a file the repo has moved past."""
    place(env, V1)
    assert record(env, env["c1"]).returncode == 0
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 1 and after_baseline(p).startswith("STALE"), p.stdout


def test_record_only_refuses_a_missing_file(env):
    p = record(env, env["c2"])
    assert p.returncode != 0 and "nothing installed to record" in p.stderr
    assert not env["manifest"].exists()


def test_record_only_refuses_a_template(env):
    filled = env["dest"] / "conf.sh"
    filled.write_bytes(b"SECRET=\"real\"\n")
    p = record(env, env["c2"], "--template", dest_name="conf.sh", src="scripts/conf.sh.example")
    assert p.returncode != 0 and "cannot check a filled template" in p.stderr
    assert not env["manifest"].exists()


def test_record_only_refuses_without_a_repo(env):
    place(env, V2)
    p = record(env, env["c2"], "--source-repo", "KTPInfrastructure", repo=False)
    assert p.returncode != 0 and "needs --repo" in p.stderr
    assert not env["manifest"].exists()


def test_record_only_refuses_the_flags_that_would_make_it_a_claim(env):
    place(env, V2)
    other = env["tmp"] / "other.sh"
    other.write_bytes(V2)
    for extra, want in (
        (["--file", str(other)], "copies nothing"),
        (["--blob-md5", md5(V2)], "restate it as a claim"),
        (["--mode", "755"], "writes no file"),
    ):
        p = record(env, env["c2"], *extra)
        assert p.returncode != 0 and want in p.stderr, (extra, p.stderr)
    assert not env["manifest"].exists()


def test_record_only_honours_expect_md5_when_given(env):
    place(env, V2)
    p = record(env, env["c2"], "--expect-md5", md5(V1))
    assert p.returncode != 0 and "not recording it" in p.stderr
    assert not env["manifest"].exists()
    p = record(env, env["c2"], "--expect-md5", md5(V2))
    assert p.returncode == 0, p.stderr


def test_record_only_refuses_an_unresolvable_commit_or_path(env):
    place(env, V2)
    p = record(env, "0" * 40)
    assert p.returncode != 0 and not env["manifest"].exists()
    p = record(env, env["c2"], src="scripts/no-such-file.sh")
    assert p.returncode != 0 and not env["manifest"].exists()


def test_record_only_refuses_a_duplicate_row(env):
    place(env, V2)
    assert record(env, env["c2"]).returncode == 0
    p = record(env, env["c2"])
    assert p.returncode != 0 and "already recorded" in p.stderr
    assert len(rows(env)) == 1


def test_record_only_re_records_the_same_bytes_at_a_newer_commit(env):
    """Bytes unchanged, row stale: the reconciliation that clears STALE without a copy."""
    place(env, V2)
    assert record(env, env["c2"]).returncode == 0
    git(env["repo"], "commit", "-q", "--allow-empty", "-m", "unrelated")
    c3 = git(env["repo"], "rev-parse", "HEAD")
    p = record(env, c3)
    assert p.returncode == 0, p.stderr
    assert [r[3] for r in rows(env)] == [env["c2"], c3]


def test_record_only_clears_a_drift_row_only_when_the_bytes_are_the_blob(env):
    """The reconciliation this mode exists for, in both directions on one manifest."""
    install(env, env["c1"], "-")
    (env["dest"] / "tool.sh").write_bytes(V2)
    assert run(env, "--report").returncode == 1
    p = record(env, env["c1"])
    assert p.returncode != 0 and "refusing to record" in p.stderr
    assert run(env, "--report").returncode == 1
    assert record(env, env["c2"]).returncode == 0
    p = run(env, "--report")
    assert p.returncode == 0 and after_baseline(p).startswith("OK"), p.stdout


def test_record_only_refuses_an_unreadable_manifest(env):
    place(env, V2)
    env["manifest"].parent.mkdir(parents=True, exist_ok=True)
    env["manifest"].write_text(HEADER + "\n/x\tshort\n")
    p = record(env, env["c2"])
    assert p.returncode != 0 and "cannot read back" in p.stderr
    assert env["manifest"].read_text() == HEADER + "\n/x\tshort\n"


def test_record_only_is_not_a_report_flag(env):
    p = run(env, "--report", "--record-only")
    assert p.returncode == 2 and "different jobs" in p.stderr, p.stderr
    p = record(env, env["c2"], "--against-ref", "HEAD")
    assert p.returncode == 2 and "--report flag" in p.stderr


def test_record_only_does_not_weaken_the_install_no_op_refusal(env):
    install(env, env["c1"], "-")
    p = install(env, env["c1"], md5(V1))
    assert p.returncode != 0 and "nothing to install" in p.stderr
    assert len(rows(env)) == 1


# --- the never-pulled deploy checkout ---------------------------------------
# /opt/ktp-infra is read on purpose and sourced from never. Both directions matter here
# more than usual: a guard that refuses every path breaks every install, and a guard that
# matches on a bare prefix would refuse an unrelated /opt/ktp-infra-something.

REFUSAL = "never-pulled deploy checkout"


def test_install_from_the_never_pulled_checkout_is_refused(env):
    p = run(env, "--repo", "/opt/ktp-infra", "--commit", env["c1"], "--src", "scripts/tool.sh",
            "--dest", str(env["dest"] / "tool.sh"), "--expect-md5", "-")
    assert p.returncode != 0
    assert REFUSAL in p.stderr
    # It must name a way forward, or the refusal is a dead end -- but a PATH is the wrong
    # kind of answer: nothing on the box pulls any checkout, so every one goes stale and
    # the advice rots. Name the route instead.
    # ⚠️ Assert on message-only wording, never on an option name: ap.error() prints argparse's
    # usage line, which lists every flag -- so `"--blob-md5" in stderr` passes even with the
    # guidance deleted. A mutation test caught that; reading it did not.
    assert "Install with --file" in p.stderr
    assert "needs no checkout" in p.stderr
    # Regression: it used to send people to the reports checkout, which was itself behind
    # and whose own ktp-install carried no guard.
    assert "/opt/ktp-reports" not in p.stderr


def test_install_from_a_subdirectory_of_it_is_also_refused(env):
    p = run(env, "--repo", "/opt/ktp-infra/scripts", "--commit", env["c1"],
            "--src", "scripts/tool.sh", "--dest", str(env["dest"] / "tool.sh"),
            "--expect-md5", "-")
    assert p.returncode != 0
    assert REFUSAL in p.stderr


def test_a_path_merely_sharing_the_prefix_is_not_refused(env):
    """/opt/ktp-infra-other is a different directory -- a bare prefix match would eat it."""
    p = run(env, "--repo", "/opt/ktp-infra-other", "--commit", env["c1"],
            "--src", "scripts/tool.sh", "--dest", str(env["dest"] / "tool.sh"),
            "--expect-md5", "-")
    assert REFUSAL not in p.stderr          # it fails, but for being no git repo, not for this


def test_report_against_that_checkout_is_not_refused(env):
    """--report --against-ref wants to READ it; only copying bytes out is the hazard."""
    p = run(env, "--report", "--repo", "/opt/ktp-infra")
    assert REFUSAL not in p.stderr


def test_a_normal_install_still_works_with_the_guard_in_place(env):
    """The positive control: the guard must refuse one path, not installs in general."""
    p = install(env, env["c1"], "-")      # '-' = nothing at the destination yet
    assert p.returncode == 0, p.stderr
    assert REFUSAL not in p.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V1
# --- the baseline itself: what a CURRENT is current WITH -------------------
#
# The defect these hold open was measured, not imagined. On the data server the
# deploy checkout's `origin/main` was 214 commits behind GitHub's, so every row
# compared against it printed CURRENT and the report exited 0 -- a freshness
# check failing in the reassuring direction, which is worse than no check. A ref
# under refs/remotes/ is a CACHE of someone else's branch and nothing on a box
# keeps it current, so the claim is checked rather than trusted. Both directions
# here: a guard that cannot pass is decoration, and one that cannot fire is too.


def _clone_of(src, dst):
    subprocess.run(["git", "clone", "-q", str(src), str(dst)], check=True, capture_output=True)


def states(out):
    """The state token of each ROW, skipping the baseline header and comments."""
    return [l.split()[0] for l in out.splitlines()
            if l.strip() and not l.startswith(("baseline ", "#"))]


@pytest.fixture
def clone(env, tmp_path):
    """A checkout whose origin/main is a cache -- the shape every live box has."""
    git(env["repo"], "branch", "-M", "main")
    c = tmp_path / "clone"
    _clone_of(env["repo"], c)
    return c


def test_a_cached_baseline_that_is_behind_is_untrusted_and_reaches_no_row(env, clone):
    """The measured failure, in miniature: the clone's origin/main is a week old.

    Nothing about the rows changed -- the installed file really is c2's bytes --
    so the old code printed CURRENT and exited 0 while the branch had moved on.
    """
    install(env, env["c2"], "-")
    (env["repo"] / "scripts" / "tool.sh").write_bytes(b"#!/bin/bash\necho v3\n")
    git(env["repo"], "commit", "-q", "-am", "v3")
    p = run(env, "--report", "--repo", str(clone), "--against-ref", "origin/main")
    assert p.returncode == 2, p.stdout
    assert states(p.stdout) == ["UNTRUSTED"], p.stdout
    # Both shas, because a reader cannot settle this from one of them.
    assert git(clone, "rev-parse", "origin/main") in p.stdout, p.stdout
    assert git(env["repo"], "rev-parse", "main") in p.stdout, p.stdout
    assert "fetch" in p.stdout, p.stdout


def test_the_same_report_runs_when_the_cache_is_the_remotes_tip(env, clone):
    """The control. A guard that cannot pass would just be the check turned off."""
    install(env, env["c2"], "-")
    p = run(env, "--report", "--repo", str(clone), "--against-ref", "origin/main")
    assert p.returncode == 0, p.stdout
    head = p.stdout.splitlines()[0]
    assert head.startswith("baseline") and "origin/main" in head, head
    assert "verified against origin refs/heads/main" in head, head
    assert states(p.stdout) == ["CURRENT"], p.stdout


def test_a_ref_that_tracks_no_remote_still_runs_and_says_so(env):
    """A sha, a tag or HEAD claims nothing, so refusing it would be noise. But a
    CURRENT against it must not be quotable as current with main, so it is
    labelled rather than refused."""
    install(env, env["c2"], "-")
    p = run(env, "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 0, p.stdout
    assert "pinned" in p.stdout.splitlines()[0], p.stdout
    assert states(p.stdout) == ["CURRENT"], p.stdout


def test_a_remote_we_cannot_reach_is_untrusted_not_fresh(env, clone, tmp_path):
    """Offline is the case that decides whether this guard is worth having: the
    reassuring answer is always available, so it has to be the one we refuse."""
    install(env, env["c2"], "-")
    git(clone, "remote", "set-url", "origin", str(tmp_path / "no-such-repo"))
    p = run(env, "--report", "--repo", str(clone), "--against-ref", "origin/main")
    assert p.returncode == 2, p.stdout
    assert states(p.stdout) == ["UNTRUSTED"], p.stdout
    assert "cannot reach origin" in p.stdout, p.stdout


def test_a_cached_branch_the_remote_no_longer_holds_is_untrusted(env, clone):
    install(env, env["c2"], "-")
    git(env["repo"], "checkout", "-q", "-b", "elsewhere")
    git(env["repo"], "branch", "-q", "-D", "main")
    p = run(env, "--report", "--repo", str(clone), "--against-ref", "origin/main")
    assert p.returncode == 2, p.stdout
    assert states(p.stdout) == ["UNTRUSTED"], p.stdout
    assert "no refs/heads/main" in p.stdout, p.stdout


def test_the_baseline_header_is_only_printed_for_a_freshness_run(env):
    """--report alone answers a different question and has no baseline to state."""
    install(env, env["c2"], "-")
    p = run(env, "--report")
    assert p.returncode == 0 and not p.stdout.startswith("baseline"), p.stdout


# --- --plan: the install step, as text that refuses rather than clobbers ----
#
# The estate had no deploy step at all; /usr/local/bin was a person remembering
# to copy a file, and the commands were hand-written each time. These hold the
# plan to the two properties that make it safe to paste: it is executable, and
# it cannot install anything but the bytes it measured.


def shim(env, tmp_path):
    """A PATH where the bare name `ktp-install` resolves, as it does on a box."""
    d = tmp_path / "shim"
    d.mkdir(exist_ok=True)
    sh = d / "ktp-install"
    sh.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, TOOL))
    os.chmod(sh, 0o755)
    return str(d)


def run_plan(env, text, tmp_path):
    e = dict(env["env"], PATH=shim(env, tmp_path) + os.pathsep + env["env"]["PATH"])
    return subprocess.run(["bash", "-e"], input=text, env=e, capture_output=True, text=True)


def test_a_plan_is_emitted_for_a_stale_row_and_running_it_makes_it_current(env, clone, tmp_path):
    """The whole point, end to end. Asserting the plan's SHAPE would prove nothing
    about whether it installs anything -- so the plan is run, and the verdict is
    the report afterwards."""
    install(env, env["c1"], "-")
    p = run(env, "--plan", "--repo", str(clone), "--against-ref", "origin/main",
            "--stage-dir", str(tmp_path / "stage"))
    assert p.returncode == 1, p.stdout + p.stderr
    assert "--expect-md5 %s" % md5(V1) in p.stdout, p.stdout
    assert "--blob-md5 %s" % md5(V2) in p.stdout, p.stdout

    r = run_plan(env, p.stdout, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V2
    after = run(env, "--report", "--repo", str(clone), "--against-ref", "origin/main")
    assert after.returncode == 0 and states(after.stdout) == ["CURRENT"], after.stdout


def test_a_plan_that_has_gone_out_of_date_refuses_instead_of_clobbering(env, clone, tmp_path):
    """A plan is a text file someone pastes later. Its --expect-md5 is what makes
    "later" safe: the box moving under it is a refusal, not a silent overwrite."""
    install(env, env["c1"], "-")
    p = run(env, "--plan", "--repo", str(clone), "--against-ref", "origin/main",
            "--stage-dir", str(tmp_path / "stage"))
    assert p.returncode == 1, p.stdout
    hotfix = b"#!/bin/bash\necho hotfix\n"
    (env["dest"] / "tool.sh").write_bytes(hotfix)
    r = run_plan(env, p.stdout, tmp_path)
    assert r.returncode != 0, r.stdout + r.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == hotfix


def test_a_plan_staged_from_the_wrong_tree_refuses(env, clone, tmp_path):
    """--blob-md5 is the second pin. Both exist because either one alone leaves a
    way for a plan to land bytes nobody measured."""
    install(env, env["c1"], "-")
    p = run(env, "--plan", "--repo", str(clone), "--against-ref", "origin/main",
            "--stage-dir", str(tmp_path / "stage"))
    lines = [l for l in p.stdout.splitlines() if not l.startswith(("#", "git -C"))]
    body = "mkdir -p %s\n" % (tmp_path / "stage")
    body += "printf 'not the blob\\n' > %s\n" % (tmp_path / "stage" / "_".join(
        str(env["dest"] / "tool.sh").lstrip("/").split("/")))
    body += "\n".join(lines)
    r = run_plan(env, body, tmp_path)
    assert r.returncode != 0, r.stdout + r.stderr
    # For the pin's reason, not some other refusal that happens to land first.
    assert "not the blob's %s" % md5(V2) in r.stderr, r.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V1


def test_a_drifted_row_is_never_planned(env, clone, tmp_path):
    """An install would discard a hand edit, and a generator must not decide that."""
    install(env, env["c1"], "-")
    (env["dest"] / "tool.sh").write_bytes(b"#!/bin/bash\necho hotfix\n")
    p = run(env, "--plan", "--repo", str(clone), "--against-ref", "origin/main")
    assert p.returncode == 0, p.stdout
    assert "ktp-install --file" not in p.stdout, p.stdout
    assert "NOT PLANNED" in p.stdout and "DRIFT" in p.stdout, p.stdout


def test_nothing_owed_is_an_empty_plan_not_an_error(env, clone):
    install(env, env["c2"], "-")
    p = run(env, "--plan", "--repo", str(clone), "--against-ref", "origin/main")
    assert p.returncode == 0, p.stdout
    assert "nothing owed" in p.stdout and "ktp-install --file" not in p.stdout, p.stdout


def test_a_plan_cannot_be_built_on_an_unauthenticated_baseline(env, clone, tmp_path):
    """The ordering that makes the step safe to have at all: without the gate this
    would generate commands installing a stale commit's bytes as though current."""
    install(env, env["c1"], "-")
    git(clone, "remote", "set-url", "origin", str(tmp_path / "no-such-repo"))
    p = run(env, "--plan", "--repo", str(clone), "--against-ref", "origin/main")
    assert p.returncode == 2, p.stdout
    assert states(p.stdout) == ["UNTRUSTED"], p.stdout
    assert "ktp-install --file" not in p.stdout, p.stdout


def test_plan_without_a_ref_is_refused(env):
    p = run(env, "--plan", "--repo", str(env["repo"]))
    assert p.returncode == 2 and "--against-ref" in p.stderr, p.stderr


def test_plan_and_report_are_not_run_together(env):
    p = run(env, "--plan", "--report", "--repo", str(env["repo"]), "--against-ref", "HEAD")
    assert p.returncode == 2 and "different jobs" in p.stderr, p.stderr


def test_stage_dir_outside_a_plan_is_refused(env):
    p = run(env, "--report", "--stage-dir", "/tmp/x")
    assert p.returncode == 2 and "--plan flag" in p.stderr, p.stderr
def test_ls_remote_cannot_stop_and_ask_for_credentials(env, clone, tmp_path):
    """A git that cannot authenticate ASKS -- and this runs from a daily unit with no
    terminal to answer. A hung unit reads as `active`, the one failure nothing in this
    estate alerts on, so the invocation must close every way of asking. The timeout is
    only the backstop; asserting on it would be asserting on the backstop.

    Measured through a shim on PATH that records the environment the real call gets, so
    this is the invocation rather than a reading of the source.
    """
    shim_dir = tmp_path / "gitshim"
    shim_dir.mkdir()
    seen = tmp_path / "ls-remote-env.txt"
    real = subprocess.run(["which", "git"], capture_output=True, text=True).stdout.strip()
    (shim_dir / "git").write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do [ "$a" = "ls-remote" ] && env > "%s"; done\n'
        'exec "%s" "$@"\n' % (seen, real))
    os.chmod(shim_dir / "git", 0o755)

    install(env, env["c2"], "-")
    e = dict(env["env"], PATH=str(shim_dir) + os.pathsep + env["env"]["PATH"])
    p = subprocess.run([sys.executable, TOOL, "--report", "--repo", str(clone),
                        "--against-ref", "origin/main"], env=e, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    recorded = dict(l.split("=", 1) for l in seen.read_text().splitlines() if "=" in l)
    assert recorded["GIT_TERMINAL_PROMPT"] == "0", recorded.get("GIT_TERMINAL_PROMPT")
    assert recorded["GIT_ASKPASS"] == "", recorded.get("GIT_ASKPASS")
    assert recorded["SSH_ASKPASS"] == "", recorded.get("SSH_ASKPASS")
    assert "BatchMode=yes" in recorded["GIT_SSH_COMMAND"], recorded.get("GIT_SSH_COMMAND")
