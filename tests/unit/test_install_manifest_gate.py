"""The install gate in `scripts/install-game-files-manifest.py`.

The generator cannot install anything — it writes a local JSON file and stops. What
changes what players are enforced against is the copy onto the AC API host, and until
this script that copy was a hand-run `scp` + `cp` with a backup convention and no
reader. So the acknowledgement sat one step away from the consequence, and the gate
that existed protected a step where nothing reaches a player.

These pin the parts that make moving it worth doing:

  1. it is ARMED BY DEFAULT — the opposite of the generator's opt-in gate, and for the
     opposite reason;
  2. it gates on SEVERITY, not just membership. `review` -> `violation` widens what a
     player is scored on without adding a single path, and `_meta.version` does not
     cover severity, so nothing else in the pipeline notices;
  3. an unrankable severity refuses rather than being treated as harmless;
  4. it takes the backup itself, before the write, and publishes by rename so the
     path never holds a half-written document;
  5. no baseline means REFUSE, where the generator warns and writes anyway.

Loaded by path with `paramiko` stubbed, the same way the generator's guards next door
do it.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "install-game-files-manifest.py"


@pytest.fixture(scope="module")
def mod():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_install_manifest_gate", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def gen(mod):
    return mod.load_generator()


def entry(path, severity="violation", origin=".res", sha=None):
    return {"path": path, "sha256": sha or "0" * 64, "size": 1, "origin": origin,
            "severity": severity, "category": "model_other"}


def manifest(entries, version="v0"):
    entries = list(entries)
    return {
        "_meta": {"version": version, "total_files": len(entries),
                  "by_severity": {}, "by_category": {}, "sources": {}},
        "files": entries,
    }


def diff_of(gen, before, after):
    return gen.diff_manifests(manifest(before), manifest(after))


def run_gate(mod, gen, diff, alternates=((), ()), **acks):
    out = io.StringIO()
    ok = mod.gate_install(diff, mod.Acknowledgements(**acks), gen.enforced_changes,
                          alternates, out=out)
    return ok, out.getvalue()


# --------------------------------------------------------------------------
# Severity — the change a membership gate cannot see
# --------------------------------------------------------------------------

def test_review_to_violation_is_a_widening(mod):
    assert mod.classify_severity_change("review", "violation") == "widened"


def test_violation_to_review_is_a_narrowing(mod):
    assert mod.classify_severity_change("violation", "review") == "narrowed"


@pytest.mark.parametrize("before,after", [("review", "quarantine"),
                                          ("quarantine", "violation"),
                                          ("", "violation"),
                                          ("violation", None)])
def test_an_unrankable_severity_is_never_ranked_harmless(mod, before, after):
    """The trap this avoids is a `.get(sev, 0)` default.

    A severity added to the generator's policy later would arrive here, rank as the
    weakest thing there is, and every transition involving it would read as a
    narrowing or as nothing at all — the gate passing precisely on the change nobody
    has looked at yet.
    """
    assert mod.classify_severity_change(before, after) == "unknown"


def test_a_severity_flip_alone_refuses_a_membership_clean_install(mod, gen):
    """The headline case: same paths, same hashes, strictly more enforcement.

    A membership-only gate sees an empty added[] and an empty removed[] and passes.
    So does `_meta.version`, which hashes paths, hashes and alternates and not
    severity. This is the only thing in the pipeline that stops.
    """
    before = [entry("models/p_garand_l.mdl", "review")]
    after = [entry("models/p_garand_l.mdl", "violation")]
    d = diff_of(gen, before, after)

    assert d["added"] == [] and d["removed"] == []
    assert gen.enforced_changes(d["added"]) == []

    ok, text = run_gate(mod, gen, d)
    assert ok is False
    assert "--accept-widened 1" in text


def test_the_widening_count_must_match_exactly(mod, gen):
    """A count pasted out of a runbook stops agreeing the moment one more path flips."""
    before = [entry(f"models/p_{n}_l.mdl", "review") for n in ("garand", "k98s", "spring")]
    after = [entry(f"models/p_{n}_l.mdl", "violation") for n in ("garand", "k98s", "spring")]
    d = diff_of(gen, before, after)

    ok, text = run_gate(mod, gen, d, widened=2)
    assert ok is False
    assert "does not match" in text

    ok, text = run_gate(mod, gen, d, widened=3)
    assert ok is True
    assert "accepted: 3" in text


def test_a_narrowing_gates_on_its_own_flag(mod, gen):
    """Coverage loss is a decision too, and acknowledging a widening must not cover it."""
    d = diff_of(gen, [entry("gfx/env/skyup.tga", "violation")],
                [entry("gfx/env/skyup.tga", "review")])

    assert run_gate(mod, gen, d)[0] is False
    assert run_gate(mod, gen, d, widened=1)[0] is False
    assert run_gate(mod, gen, d, narrowed=1)[0] is True


def test_an_unrankable_transition_has_no_accept_flag(mod, gen):
    """There is nothing to acknowledge a count of when the direction is unknown.

    The fix is a reviewed commit teaching SEVERITY_RANK the new value, so no flag
    combination may talk past it.
    """
    d = diff_of(gen, [entry("models/p_garand.mdl", "review")],
                [entry("models/p_garand.mdl", "quarantine")])

    for acks in ({}, {"widened": 1}, {"narrowed": 1}, {"widened": 1, "narrowed": 1}):
        ok, text = run_gate(mod, gen, d, **acks)
        assert ok is False
        assert "cannot rank" in text


def test_the_verdict_classifies_rather_than_relisting_what_the_diff_printed(mod, gen):
    """The generator has already listed every flipped path under SEVERITY CHANGED. What
    it cannot say is which of them widen, and that is the only thing the gate acts on."""
    before = [entry("a.mdl", "review"), entry("b.mdl", "review"), entry("c.mdl", "violation")]
    after = [entry("a.mdl", "violation"), entry("b.mdl", "violation"), entry("c.mdl", "review")]
    text = "\n".join(mod.format_severity_verdict(
        mod.severity_transitions(diff_of(gen, before, after))))

    assert "WIDENS enforcement : 2" in text, text
    assert "NARROWS enforcement: 1" in text, text
    assert "a.mdl" not in text, "paths were already printed once; this classifies them"


def test_an_unrankable_severity_is_named_path_by_path(mod, gen):
    """It refuses and no flag covers it, so the reader has to go and look at the paths."""
    d = diff_of(gen, [entry("a.mdl", "review")], [entry("a.mdl", "quarantine")])
    text = "\n".join(mod.format_severity_verdict(mod.severity_transitions(d)))
    assert "UNRECOGNISED" in text and "a.mdl" in text


def test_no_severity_movement_prints_no_section(mod, gen):
    d = diff_of(gen, [entry("a.mdl")], [entry("a.mdl", sha="1" * 64)])
    assert mod.format_severity_verdict(mod.severity_transitions(d)) == []


def test_severity_buckets_never_double_count_a_membership_change(mod, gen):
    """`severity_changed` is computed over paths on both sides, so a path cannot be
    counted once as added and again as widened."""
    d = diff_of(gen,
                [entry("a.mdl", "review")],
                [entry("a.mdl", "violation"), entry("b.mdl", "violation")])
    buckets = mod.severity_transitions(d)
    assert [p for p, _, _ in buckets["widened"]] == ["a.mdl"]
    assert [e["path"] for e in d["added"]] == ["b.mdl"]


# --------------------------------------------------------------------------
# Membership — parity with the generator's gate
# --------------------------------------------------------------------------

def test_membership_changes_still_gate_with_their_own_counts(mod, gen):
    d = diff_of(gen, [entry("a.mdl"), entry("b.mdl")], [entry("a.mdl"), entry("c.mdl")])

    assert run_gate(mod, gen, d)[0] is False
    assert run_gate(mod, gen, d, added=1)[0] is False          # removal unacknowledged
    assert run_gate(mod, gen, d, added=1, removed=1)[0] is True


def test_an_added_review_path_does_not_gate(mod, gen):
    """A `review` entry is captured and never scores, so adding one changes what is
    disclosed rather than what is enforced. It is printed; it does not refuse."""
    d = diff_of(gen, [entry("a.mdl")], [entry("a.mdl"), entry("gfx/env/skyup.tga", "review")])
    ok, text = run_gate(mod, gen, d)
    assert ok is True
    assert "nothing enforced entered or left scope" in text


def test_a_count_for_a_change_that_has_since_vanished_refuses(mod, gen):
    """`--accept-added 14` against a diff that now adds nothing is the same staleness as
    a count that is too low: the manifest moved between reading it and installing it."""
    d = diff_of(gen, [entry("a.mdl")], [entry("a.mdl")])
    ok, text = run_gate(mod, gen, d, added=14)
    assert ok is False
    assert "does not match the 0" in text


def test_a_clean_diff_passes_and_says_so(mod, gen):
    d = diff_of(gen, [entry("a.mdl")], [entry("a.mdl", sha="1" * 64)])
    ok, text = run_gate(mod, gen, d)
    assert ok is True
    assert "no severity moved" in text


def test_added_and_removed_cannot_cancel_out(mod, gen):
    """Four independent counts rather than one total: an addition and a removal in the
    same run are two decisions, and a single net figure would net them to nothing."""
    d = diff_of(gen, [entry("a.mdl")], [entry("b.mdl")])
    assert len(gen.enforced_changes(d["added"])) == 1
    assert len(gen.enforced_changes(d["removed"])) == 1
    assert run_gate(mod, gen, d, added=1)[0] is False
    assert run_gate(mod, gen, d, removed=1)[0] is False


# --------------------------------------------------------------------------
# Allowed alternate hashes — the third axis neither existing control sees
# --------------------------------------------------------------------------

def alt_entry(path, alternates, severity="violation"):
    e = entry(path, severity)
    if alternates is not None:
        e["allowed_alternate_hashes"] = list(alternates)
    return e


def test_dropping_an_alternate_widens_with_no_path_severity_or_hash_change(mod, gen):
    """🔴 The worst case this tool exists to catch, and the one the generator's diff
    describes as "no change: same paths, same severities, same hashes". An operator-
    curated alternate is what keeps a legitimate community file from scoring; removing
    it makes every holder of that file a violation, with nothing else moving."""
    before = [alt_entry("models/p_garand.mdl", ["a" * 64])]
    after = [alt_entry("models/p_garand.mdl", None)]

    d = diff_of(gen, before, after)
    assert d["added"] == [] and d["removed"] == [] and d["severity_changed"] == []
    assert d["rehashed"] == 0

    dropped, gained = mod.alternate_transitions(manifest(before), manifest(after))
    assert [p for p, _ in dropped] == ["models/p_garand.mdl"]
    assert gained == []

    ok, text = run_gate(mod, gen, d, alternates=(dropped, gained))
    assert ok is False
    assert "--accept-alternates-dropped 1" in text


def test_gaining_an_alternate_gates_on_its_own_flag(mod, gen):
    before = [alt_entry("a.mdl", None)]
    after = [alt_entry("a.mdl", ["b" * 64])]
    d = diff_of(gen, before, after)
    dropped, gained = mod.alternate_transitions(manifest(before), manifest(after))

    assert run_gate(mod, gen, d, alternates=(dropped, gained))[0] is False
    assert run_gate(mod, gen, d, alternates=(dropped, gained),
                    alternates_dropped=1)[0] is False
    assert run_gate(mod, gen, d, alternates=(dropped, gained),
                    alternates_gained=1)[0] is True


def test_an_alternate_on_a_review_path_does_not_gate(mod):
    """A `review` entry never scores, so its alternates cannot change what a player is
    scored on in either direction."""
    before = [alt_entry("gfx/env/skyup.tga", ["a" * 64], severity="review")]
    after = [alt_entry("gfx/env/skyup.tga", None, severity="review")]
    assert mod.alternate_transitions(manifest(before), manifest(after)) == ([], [])


def test_an_alternate_change_counts_when_severity_moves_with_it(mod):
    """Enforced on EITHER side, so a path that drops an alternate in the same install
    that makes it score is not lost between the two checks."""
    before = [alt_entry("a.mdl", ["a" * 64], severity="review")]
    after = [alt_entry("a.mdl", None, severity="violation")]
    dropped, _ = mod.alternate_transitions(manifest(before), manifest(after))
    assert [p for p, _ in dropped] == ["a.mdl"]


def test_an_added_path_is_not_also_an_alternate_change(mod):
    """Only paths on both sides — an added path is already counted by the membership
    gate, and counting it twice would ask for two acknowledgements of one decision."""
    before = []
    after = [alt_entry("a.mdl", ["a" * 64])]
    assert mod.alternate_transitions(manifest(before), manifest(after)) == ([], [])


def test_the_alternate_verdict_names_the_hashes(mod):
    dropped = [("models/p_garand.mdl", ["a" * 64])]
    text = chr(10).join(mod.format_alternate_verdict(dropped, []))
    assert "ALTERNATES DROPPED" in text
    assert "models/p_garand.mdl" in text
    assert "a" * 64 in text


def test_no_alternate_movement_prints_no_section(mod):
    assert mod.format_alternate_verdict([], []) == []


# --------------------------------------------------------------------------
# Backup naming
# --------------------------------------------------------------------------

def test_backup_sits_beside_the_manifest_and_is_readable_in_an_ls(mod):
    from datetime import datetime, timezone
    when = datetime(2026, 9, 23, tzinfo=timezone.utc)
    name = mod.backup_name("/opt/ktp-ac-api/game_files_manifest.json", "pre-weapon-kit", when)
    assert name == "/opt/ktp-ac-api/game_files_manifest.json.bak-pre-weapon-kit-20260923"


def test_a_second_install_the_same_day_gets_a_distinct_name(mod):
    """The collision would replace the only copy of what was live this morning with a
    copy of what has been live since lunchtime — the rollback target becoming the thing
    you are rolling back from."""
    from datetime import datetime, timezone
    when = datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)
    first = mod.backup_name("/opt/ktp-ac-api/m.json", "fix", when)
    second = mod.backup_name("/opt/ktp-ac-api/m.json", "fix", when, attempt=1)

    assert second != first
    assert second.endswith("-140509")


def test_a_reason_cannot_steer_the_backup_out_of_the_directory(mod):
    """`--reason` reaches a path, and a slash in it would write the backup somewhere
    other than beside the manifest — including on top of something else."""
    name = mod.backup_name("/opt/ktp-ac-api/m.json", "../../etc/cron.d/oops")
    assert "/etc/" not in name
    assert name.startswith("/opt/ktp-ac-api/m.json.bak-")


# --------------------------------------------------------------------------
# The copy itself
# --------------------------------------------------------------------------

class FakeFile(io.BytesIO):
    def __init__(self, sftp, path, mode):
        super().__init__(sftp.files.get(path, b"") if "r" in mode else b"")
        self._sftp, self._path, self._mode = sftp, path, mode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if "w" in self._mode:
            if self._sftp.fail_on_close and self._sftp.fail_on_close in self._path:
                raise OSError("disk full at flush")
            self._sftp.files[self._path] = self.getvalue()
        self.close()
        return False


class FakeSFTP:
    """Just enough SFTP to watch the order of operations, faithful where it matters.

    ⚠️ A write-mode `open` CREATES the entry immediately, because paramiko sends
    SSH_FXP_OPEN with CREATE|TRUNC inside `open()` — the file exists the moment it
    returns. A fake that only materialised the file on close cannot produce the one
    state the staged-file cleanup exists for, so the test guarding that cleanup passes
    with the cleanup deleted. `fail_on_close` reproduces the real failure point.
    """

    def __init__(self, files=None, fail_on_close=None, rename_fails=False,
                 remove_fails=False):
        self.files = dict(files or {})
        self.log = []
        self.fail_on_close = fail_on_close
        self.rename_fails = rename_fails
        self.remove_fails = remove_fails

    def open(self, path, mode="r"):
        if "w" in mode:
            if "x" in mode and path in self.files:
                raise OSError(f"File exists: {path}")
            self.files[path] = b""          # CREATE|TRUNC happens here, not at close
            self.log.append(("write", path))
        else:
            if path not in self.files:
                raise OSError(f"No such file: {path}")
            self.log.append(("read", path))
        return FakeFile(self, path, mode)

    def stat(self, path):
        self.log.append(("stat", path))
        if path not in self.files:
            raise OSError(f"No such file: {path}")
        return object()

    def chmod(self, path, mode):
        self.log.append(("chmod", path, mode))

    def posix_rename(self, src, dst):
        self.log.append(("rename", src, dst))
        if self.rename_fails:
            raise OSError("posix-rename@openssh.com not supported")
        self.files[dst] = self.files.pop(src)

    def remove(self, path):
        self.log.append(("remove", path))
        if self.remove_fails:
            raise OSError("permission denied")
        self.files.pop(path, None)


LIVE = "/opt/ktp-ac-api/game_files_manifest.json"


def staged_paths(sftp):
    return [p for p in sftp.files if ".installing" in p]


def backups(sftp):
    return [p for p in sftp.files if p.startswith(LIVE + ".bak-")]


def test_the_backup_is_taken_before_the_write(mod):
    """Not a convention someone remembers: the copy that preserves the rollback happens
    in the same call that replaces the file."""
    sftp = FakeSFTP({LIVE: b'{"files": []}'})
    backup = mod.install(sftp, LIVE, b'{"files": [1]}', "pre-weapon-kit",
                         had_previous=True, out=io.StringIO())

    assert sftp.files[backup] == b'{"files": []}'
    assert sftp.files[LIVE] == b'{"files": [1]}'
    writes = [i for i, ev in enumerate(sftp.log) if ev[0] == "write"]
    assert sftp.log[writes[0]][1] == backup, "the backup must be the first thing written"


def test_an_existing_backup_is_never_clobbered(mod):
    """The guarantee is O_EXCL, not a directory listing. A listing is a CHECK, and a
    check that cannot read the directory has to fail open or refuse; the server refusing
    the create needs no answer from us and reads nothing."""
    taken = mod.backup_name(LIVE, "fix")
    sftp = FakeSFTP({LIVE: b"live", taken: b"PRECIOUS"})

    backup = mod.install(sftp, LIVE, b"new", "fix", had_previous=True, out=io.StringIO())

    assert backup != taken
    assert sftp.files[taken] == b"PRECIOUS"
    assert sftp.files[backup] == b"live"


def test_the_backup_is_chmodded_to_0644(mod):
    sftp = FakeSFTP({LIVE: b"live"})
    backup = mod.install(sftp, LIVE, b"new", "r", had_previous=True, out=io.StringIO())
    assert ("chmod", backup, 0o644) in sftp.log
    assert ("chmod", staged_of(sftp), 0o644) in sftp.log


def staged_of(sftp):
    return next(ev[1] for ev in sftp.log if ev[0] == "rename")


def test_the_live_path_is_never_opened_for_writing(mod):
    """The API caches on mtime alone and serves whatever bytes are there, so a partial
    write is served as gospel. Staging beside the target and renaming means the path
    only ever holds a complete document."""
    sftp = FakeSFTP({LIVE: b'{"files": []}'})
    mod.install(sftp, LIVE, b'{"files": [1]}', "r", had_previous=True, out=io.StringIO())

    assert ("write", LIVE) not in sftp.log
    assert any(ev[0] == "rename" and ev[2] == LIVE for ev in sftp.log)


def test_every_mutating_operation_stays_on_the_manifests_own_name(mod):
    """`/opt/ktp-ac-api/` also holds `uploads/` — the evidence corpus — and `releases/`.

    Nothing lists, globs or removes a directory at all: the backup's exclusivity comes
    from O_EXCL rather than from reading what else is in there.
    """
    sftp = FakeSFTP({LIVE: b'{"files": []}'})
    mod.install(sftp, LIVE, b'{"files": [1]}', "r", had_previous=True, out=io.StringIO())

    assert sftp.log, "the fake recorded nothing — this would pass without the code running"
    for event in sftp.log:
        assert event[0] != "listdir"
        for arg in event[1:]:
            if isinstance(arg, str):
                assert arg.startswith(LIVE), f"{event} escaped the manifest path"


def test_a_corrupt_staged_file_is_never_published(mod):
    """🔴 The read-back is BEFORE the rename. Verifying afterwards detects a bad write
    only once the API is serving it — and with max-age=300 it has propagated before
    anyone reads the error. paramiko's SFTPFile._close() swallows the errors raised on
    the CMD_CLOSE round-trip, so a server-side short write need not raise at all."""
    sftp = FakeSFTP({LIVE: b"GOOD"})
    real_open = sftp.open

    def truncating_open(path, mode="r"):
        f = real_open(path, mode)
        if "w" in mode and ".installing" in path:
            sftp.files[path] = b"TRUNCATED"     # what actually lands on the server
            return io.BytesIO()                 # our write goes nowhere
        return f

    sftp.open = truncating_open
    with pytest.raises(RuntimeError, match="untouched"):
        mod.install(sftp, LIVE, b"NEW", "r", had_previous=True, out=io.StringIO())

    assert sftp.files[LIVE] == b"GOOD", "the corrupt file reached the live path"
    assert staged_paths(sftp) == []


def test_a_failed_stage_removes_itself_and_leaves_the_live_file_alone(mod):
    sftp = FakeSFTP({LIVE: b'{"files": []}'}, fail_on_close=".installing")
    with pytest.raises(OSError):
        mod.install(sftp, LIVE, b"x", "r", had_previous=True, out=io.StringIO())

    assert sftp.files[LIVE] == b'{"files": []}'
    assert any(ev[0] == "remove" for ev in sftp.log), "the staged file was never removed"
    assert staged_paths(sftp) == []


def test_a_rename_the_server_cannot_do_leaves_nothing_behind(mod):
    """A server without posix-rename@openssh.com raises rather than doing a non-atomic
    unlink-then-write. The staged file must not survive that."""
    sftp = FakeSFTP({LIVE: b"live"}, rename_fails=True)
    with pytest.raises(OSError):
        mod.install(sftp, LIVE, b"new", "r", had_previous=True, out=io.StringIO())

    assert sftp.files[LIVE] == b"live"
    assert staged_paths(sftp) == []


def test_a_cleanup_that_itself_fails_does_not_mask_the_original_error(mod):
    sftp = FakeSFTP({LIVE: b"live"}, rename_fails=True, remove_fails=True)
    out = io.StringIO()
    with pytest.raises(OSError, match="posix-rename"):
        mod.install(sftp, LIVE, b"new", "r", had_previous=True, out=out)
    assert "delete it by hand" in out.getvalue()


def test_a_first_install_takes_no_backup_of_nothing(mod):
    sftp = FakeSFTP({})
    assert mod.install(sftp, LIVE, b"x", "r", had_previous=False, out=io.StringIO()) is None
    assert sftp.files[LIVE] == b"x"
    assert backups(sftp) == []


def test_two_runs_do_not_share_one_staged_path(mod):
    sftp = FakeSFTP({LIVE: b"live"})
    mod.install(sftp, LIVE, b"new", "r", had_previous=True, out=io.StringIO())
    assert staged_of(sftp).startswith(LIVE + ".installing.")


# --------------------------------------------------------------------------
# main() — arming, and what happens with nothing to compare against
# --------------------------------------------------------------------------

class FakeSSH:
    def __init__(self, sftp, config_value=""):
        self._sftp, self._config = sftp, config_value

    def open_sftp(self):
        return self._sftp

    def exec_command(self, cmd, **kw):
        return None, io.BytesIO(self._config.encode()), io.BytesIO(b"")

    def close(self):
        pass


def run_main(mod, monkeypatch, tmp_path, sftp, argv, config_value=""):
    monkeypatch.setattr(mod, "connect", lambda *a, **k: FakeSSH(sftp, config_value))
    return mod.main(argv)


def write_candidate(tmp_path, entries):
    p = tmp_path / "candidate.json"
    p.write_text(json.dumps(manifest(entries)), encoding="utf-8")
    return str(p)


BASE_ARGS = ["--server", "example.invalid", "--reason", "test"]


def test_the_gate_is_armed_without_asking(mod, monkeypatch, tmp_path, capsys):
    """No `--gate-scope` equivalent. Every run of this script changes what players are
    checked against, so the acknowledgement is the default rather than a flag."""
    sftp = FakeSFTP({LIVE: json.dumps(manifest([entry("a.mdl", "review")])).encode()})
    candidate = write_candidate(tmp_path, [entry("a.mdl", "violation")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE])

    assert rc == 2
    assert "--accept-widened 1" in capsys.readouterr().err
    assert sftp.files[LIVE] == json.dumps(manifest([entry("a.mdl", "review")])).encode()


def test_no_baseline_refuses_rather_than_installing_unexamined(mod, monkeypatch, tmp_path, capsys):
    """The generator prints GATE ARMED BUT NOT RUN and writes anyway, which is right
    for a local file nobody is served. Here the same situation would put an unreviewed
    manifest in front of every player, so "could not compare" must not read as "passed"."""
    sftp = FakeSFTP({})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE])

    assert rc == 2
    assert "no installed manifest to compare against" in capsys.readouterr().err
    assert LIVE not in sftp.files


def test_a_present_but_unreadable_file_refuses_even_under_no_gate(mod, monkeypatch, tmp_path, capsys):
    """It cannot be copied aside, so replacing it destroys the only copy. Treating it as
    a first install — which the read failure alone cannot distinguish — would point the
    operator at the one flag that overwrites without a backup."""
    sftp = FakeSFTP({LIVE: b"x"})
    sftp.open = lambda path, mode="r": (_ for _ in ()).throw(OSError("permission denied"))
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE, "--no-gate"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "exists but could not be read" in err
    assert sftp.files[LIVE] == b"x"


def test_a_dropped_alternate_refuses_through_the_cli(mod, monkeypatch, tmp_path, capsys):
    """End to end: the install the generator's diff calls 'no change'."""
    before = manifest([dict(entry("models/p_garand.mdl"),
                            allowed_alternate_hashes=["a" * 64])])
    sftp = FakeSFTP({LIVE: json.dumps(before).encode()})
    candidate = write_candidate(tmp_path, [entry("models/p_garand.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE])

    err = capsys.readouterr().err
    assert rc == 2
    assert "no change: same paths, same severities, same hashes" in err, \
        "the generator's diff should still describe it as no change — that is the point"
    assert "ALTERNATES DROPPED" in err
    assert "--accept-alternates-dropped 1" in err

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE,
                               "--accept-alternates-dropped", "1"])
    assert rc == 0


def test_an_unparseable_installed_file_is_still_backed_up(mod, monkeypatch, tmp_path):
    """"Is there a baseline to gate against?" and "is there a file I am about to
    destroy?" are different questions. Answering the second with the first means a
    truncated manifest — the file you would most want back — is overwritten with no copy.
    """
    sftp = FakeSFTP({LIVE: b'{"files": [ tru'})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE, "--no-gate"])

    assert rc == 0
    backups = [p for p in sftp.files if p.startswith(LIVE + ".bak-")]
    assert len(backups) == 1
    assert sftp.files[backups[0]] == b'{"files": [ tru'


def test_an_unparseable_installed_file_still_refuses_when_gated(mod, monkeypatch, tmp_path, capsys):
    """It cannot be diffed, so it is not a baseline — backing it up does not make it one."""
    sftp = FakeSFTP({LIVE: b"not json"})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE])

    assert rc == 2
    assert "not valid JSON" in capsys.readouterr().err
    assert sftp.files[LIVE] == b"not json"


def test_no_gate_is_the_break_glass_and_announces_itself(mod, monkeypatch, tmp_path, capsys):
    sftp = FakeSFTP({})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE, "--no-gate"])

    assert rc == 0
    assert "GATE DISARMED" in capsys.readouterr().err
    assert LIVE in sftp.files


def test_no_gate_with_an_accept_count_is_refused_as_contradictory(mod, monkeypatch, tmp_path):
    sftp = FakeSFTP({})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    with pytest.raises(SystemExit) as exc:
        run_main(mod, monkeypatch, tmp_path, sftp,
                 BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE,
                              "--no-gate", "--accept-added", "1"])
    assert "contradictory" in str(exc.value)


def test_an_acknowledged_install_goes_through_and_backs_itself_up(mod, monkeypatch, tmp_path, capsys):
    sftp = FakeSFTP({LIVE: json.dumps(manifest([entry("a.mdl", "review")])).encode()})
    candidate = write_candidate(tmp_path, [entry("a.mdl", "violation")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE,
                               "--accept-widened", "1"])

    assert rc == 0
    assert json.loads(sftp.files[LIVE])["files"][0]["severity"] == "violation"
    assert any(p.startswith(LIVE + ".bak-") for p in sftp.files)
    assert "rollback:" in capsys.readouterr().err


def test_dry_run_reports_the_verdict_and_writes_nothing(mod, monkeypatch, tmp_path, capsys):
    original = json.dumps(manifest([entry("a.mdl", "review")])).encode()
    sftp = FakeSFTP({LIVE: original})
    candidate = write_candidate(tmp_path, [entry("a.mdl", "violation")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE,
                               "--accept-widened", "1", "--dry-run"])

    assert rc == 0
    assert sftp.files[LIVE] == original
    assert not any(p.startswith(LIVE + ".bak-") for p in sftp.files)
    assert "stopping before the copy" in capsys.readouterr().err


def test_an_identical_manifest_is_not_reinstalled(mod, monkeypatch, tmp_path, capsys):
    """Re-installing the same bytes would back a file up against its own twin and move
    the mtime the API's cache is keyed on, for no change at all."""
    candidate = write_candidate(tmp_path, [entry("a.mdl")])
    sftp = FakeSFTP({LIVE: Path(candidate).read_bytes()})

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE])

    assert rc == 0
    assert "byte-identical" in capsys.readouterr().err
    assert not any(p.startswith(LIVE + ".bak-") for p in sftp.files)


def test_the_installed_path_comes_from_the_api_config(mod, monkeypatch, tmp_path, capsys):
    """A manifest installed at the documented path while the API reads another one is an
    install that changed nothing and reported success."""
    elsewhere = "/srv/ac/manifest.json"
    sftp = FakeSFTP({elsewhere: json.dumps(manifest([entry("a.mdl")])).encode()})
    candidate = write_candidate(tmp_path, [entry("a.mdl", sha="1" * 64)])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate], config_value=elsewhere)

    assert rc == 0
    assert json.loads(sftp.files[elsewhere])["files"][0]["sha256"] == "1" * 64
    assert "NOT the default" in capsys.readouterr().err


def test_a_host_must_be_named(mod, monkeypatch, tmp_path):
    monkeypatch.delenv("KTP_AC_API_HOST", raising=False)
    candidate = write_candidate(tmp_path, [entry("a.mdl")])
    with pytest.raises(SystemExit) as exc:
        mod.main(["--manifest", candidate, "--reason", "test"])
    assert "--server is required" in str(exc.value)
