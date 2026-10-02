"""ktp-data-server-health.sh: the AC weapon-context store is watched.

The store is the only copy of a session's weapon timeline once the database rows
behind it are swept, and its files carry victim SteamIDs. Before this check
nothing looked at it: not its mode, not whether a write died half-way, and not
whether the writer was still keeping up with uploads.

The scanner is extracted from the shipped script by marker. Every timestamp is
set relative to a fixed `now`, so nothing depends on the clock.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
# On a Windows workstation "bash" resolves to WSL's, which cannot see these
# paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")

NOW = 1790000000
DAY = 86400


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def touch(path, epoch):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    os.utime(path, (epoch, epoch))


def scan(tmp_path, store, uploads, owner=None):
    probe = tmp_path / "probe.sh"
    probe.write_text(
        "set -Eeuo pipefail\n"
        "WEAPON_CONTEXT_TMP_MAX_SEC=3600\n"
        "WEAPON_CONTEXT_STALE_DAYS=7\n"
        "WEAPON_CONTEXT_STALE_MIN_BUNDLES=20\n"
        "WEAPON_CONTEXT_GRACE_SEC=7200\n"
        # Production expects root; here, whoever runs the test unless it says otherwise.
        'WEAPON_CONTEXT_OWNER_UID="${KTP_TEST_OWNER:-$(stat -c %u "$1" 2>/dev/null || true)}"\n'
        # Where the filesystem keeps no POSIX modes (a Windows checkout), report the
        # mode the test chmod'ed rather than the 755 the filesystem invents.
        'if [ -n "${KTP_TEST_MODE:-}" ]; then\n'
        '  stat() { if [ "$1 $2" = "-c %a %u" ]; then echo "$KTP_TEST_MODE $(command stat -c %u "$3")";'
        ' else command stat "$@"; fi; }\n'
        'fi\n'
        + block("ktp-weapon-context")
        + 'weapon_context_scan "$1" "$2" "$3"\n',
        encoding="utf-8", newline="\n")
    full = dict(os.environ, MSYS_NO_PATHCONV="1", MSYS2_ARG_CONV_EXCL="*")
    if owner is not None:
        full["KTP_TEST_OWNER"] = owner
    if not mode_sticks(tmp_path):
        full["KTP_TEST_MODE"] = "%o" % _MODES.get(store, 0o750)
    r = subprocess.run(
        [BASH, probe.as_posix(), store.as_posix(), uploads.as_posix(), str(NOW)],
        capture_output=True, text=True, env=full, timeout=60)
    assert r.returncode == 0, r.stderr
    return dict(line.split("\t", 1) for line in r.stdout.splitlines() if line)


_MODES = {}


def make_store(tmp_path, mode=0o750):
    store = tmp_path / "weapon-context"
    store.mkdir()
    (store / "tmp").mkdir()
    os.chmod(store, mode)
    _MODES[store] = mode
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    return store, uploads


def mode_sticks(tmp_path):
    p = tmp_path / "modeprobe"
    p.mkdir(exist_ok=True)
    os.chmod(p, 0o750)
    r = subprocess.run([BASH, "-c", 'stat -c %a "$1"', "_", p.as_posix()],
                       capture_output=True, text=True,
                       env=dict(os.environ, MSYS_NO_PATHCONV="1"))
    return r.stdout.strip() == "750"


def sidecar(store, session, epoch):
    touch(store / str(session // 1000) / ("%d.weapons.json" % session), epoch)


def bundles(uploads, count, epoch):
    for i in range(count):
        touch(uploads / "2026-10-01" / ("b%03d.zip" % i), epoch)


# --- healthy shapes ----------------------------------------------------------


def test_a_fresh_store_with_recent_sidecars_is_quiet(tmp_path):
    store, uploads = make_store(tmp_path)
    sidecar(store, 123456, NOW - 3600)
    bundles(uploads, 40, NOW - 3 * 3600)
    assert scan(tmp_path, store, uploads) == {}


def test_a_quiet_fortnight_with_no_uploads_is_quiet(tmp_path):
    """Players only run the AC on match days; no bundles means nothing to write."""
    store, uploads = make_store(tmp_path)
    sidecar(store, 123456, NOW - 14 * DAY)
    bundles(uploads, 40, NOW - 14 * DAY - 3600)
    assert scan(tmp_path, store, uploads) == {}


def test_a_few_bundles_without_sidecars_are_not_enough(tmp_path):
    """A bundle that brought its own timeline legitimately produces no sidecar."""
    store, uploads = make_store(tmp_path)
    sidecar(store, 123456, NOW - 10 * DAY)
    bundles(uploads, 19, NOW - 2 * DAY)
    assert scan(tmp_path, store, uploads) == {}


def test_bundles_inside_the_recompute_grace_do_not_count(tmp_path):
    store, uploads = make_store(tmp_path)
    sidecar(store, 123456, NOW - 10 * DAY)
    bundles(uploads, 40, NOW - 600)
    assert scan(tmp_path, store, uploads) == {}


def test_a_recent_tmp_file_is_a_write_in_progress(tmp_path):
    store, uploads = make_store(tmp_path)
    touch(store / "tmp" / ("a" * 32), NOW - 60)
    assert scan(tmp_path, store, uploads) == {}


# --- faults ------------------------------------------------------------------


def test_absent_store(tmp_path):
    out = scan(tmp_path, tmp_path / "nope", tmp_path)
    assert list(out) == ["weapon-context-store=absent"]


def test_a_store_wider_than_0750_is_reported(tmp_path):
    store, uploads = make_store(tmp_path, mode=0o755)
    out = scan(tmp_path, store, uploads)
    assert list(out) == ["weapon-context-store=too-open"]
    assert "755" in out["weapon-context-store=too-open"]


@pytest.mark.parametrize("mode", [0o750, 0o700])
def test_0750_or_tighter_is_fine(tmp_path, mode):
    store, uploads = make_store(tmp_path, mode=mode)
    assert scan(tmp_path, store, uploads) == {}


def test_a_store_owned_by_someone_else_is_reported(tmp_path):
    store, uploads = make_store(tmp_path)
    out = scan(tmp_path, store, uploads, owner="424242")
    assert list(out) == ["weapon-context-store=not-root-owned"]


def test_a_stale_tmp_file_is_a_write_that_died(tmp_path):
    store, uploads = make_store(tmp_path)
    touch(store / "tmp" / ("b" * 32), NOW - 2 * 3600)
    out = scan(tmp_path, store, uploads)
    assert list(out) == ["weapon-context-store=stale-tmp"]
    assert out["weapon-context-store=stale-tmp"].startswith("1 in-flight")


def test_bundles_kept_arriving_after_the_last_sidecar(tmp_path):
    store, uploads = make_store(tmp_path)
    sidecar(store, 123456, NOW - 10 * DAY)
    bundles(uploads, 25, NOW - 3 * DAY)
    out = scan(tmp_path, store, uploads)
    assert list(out) == ["weapon-context-store=stale"]
    assert out["weapon-context-store=stale"].startswith("25 session bundle(s)")
    assert "10d ago" in out["weapon-context-store=stale"]


def test_the_key_does_not_carry_the_count(tmp_path):
    """A count in the key would read as a recovery plus a new failure each hour."""
    store, uploads = make_store(tmp_path)
    sidecar(store, 123456, NOW - 10 * DAY)
    bundles(uploads, 25, NOW - 3 * DAY)
    first = set(scan(tmp_path, store, uploads))
    bundles(uploads, 30, NOW - 3 * DAY)
    assert set(scan(tmp_path, store, uploads)) == first


def test_an_enabled_store_that_never_wrote(tmp_path):
    store, uploads = make_store(tmp_path)
    os.utime(store, (NOW - 9 * DAY, NOW - 9 * DAY))
    bundles(uploads, 25, NOW - 3 * DAY)
    assert list(scan(tmp_path, store, uploads)) == ["weapon-context-store=never-written"]


def test_tmp_files_are_not_sidecars(tmp_path):
    """A fresh tmp file must not stand in for a sidecar that was never renamed."""
    store, uploads = make_store(tmp_path)
    sidecar(store, 123456, NOW - 10 * DAY)
    touch(store / "tmp" / "123456.weapons.json", NOW - 60)
    bundles(uploads, 25, NOW - 3 * DAY)
    assert list(scan(tmp_path, store, uploads)) == ["weapon-context-store=stale"]


def test_missing_uploads_dir_is_unmeasurable_not_fine(tmp_path):
    store, _ = make_store(tmp_path)
    sidecar(store, 123456, NOW - 10 * DAY)
    out = scan(tmp_path, store, tmp_path / "no-uploads")
    assert list(out) == ["weapon-context-store=unmeasurable"]


def test_the_scan_is_wired_into_the_down_set():
    text = SCRIPT.read_text(encoding="utf-8")
    call = text.split("# <<< ktp-weapon-context", 1)[1].split("# ---- Build sorted lists", 1)[0]
    assert 'weapon_context_scan "$WEAPON_CONTEXT_DIR" "$AC_UPLOADS_DIR" "$now_epoch"' in call
    assert 'down+=("$_key")' in call
    assert "weapon-context-store=scan-failed" in call
