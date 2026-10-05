"""ktp-corpus-offsite.sh: the AC weapon-context sidecars leave the data server too.

Once the nightly sweep deletes the database rows behind a session, its sidecar
is the only copy of which weapon was in hand. The corpus leg shipped bundles
only, so the store had no offsite copy at all. These tests drive the shipped
offsite and restore scripts end to end against a local "archive" reached
through a shim transport, on synthetic random bytes only.

The sidecars are rewritten in place, so the far side has to keep every version
while the restore takes the current one; that is asserted directly.

Uses the real `age` when it is installed and a stand-in otherwise. The stand-in
is not encryption -- it exists so the plumbing (selection, naming, manifests,
prefixes, refusal) is exercised on a runner without `age`.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(os.environ.get("KTP_CORPUS_SCRIPTS_DIR",
                              Path(__file__).resolve().parents[2] / "scripts"))
OFFSITE = SCRIPTS / "ktp-corpus-offsite.sh"
RESTORE = SCRIPTS / "ktp-corpus-restore.sh"
DRILL = SCRIPTS / "ktp-corpus-drill.sh"

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or shutil.which("rsync") is None,
    reason="needs bash, GNU coreutils and rsync",
)

FAKE_AGE = r"""#!/bin/bash
mode=enc; recips=(); key=; out=; in=
while [ $# -gt 0 ]; do
    case "$1" in
        -d) mode=dec; shift ;;
        -r) recips+=( "$2" ); shift 2 ;;
        -i) key="$2"; shift 2 ;;
        -o) out="$2"; shift 2 ;;
        *)  in="$1"; shift ;;
    esac
done
if [ "$mode" = enc ]; then
    { echo "age-encryption.org/v1 test-stand-in"; echo "${recips[*]}"; base64 -w0 < "$in"; echo; } > "$out"
else
    pub=$(sed -n 's/^# public key: //p' "$key")
    case " $(sed -n 2p "$in") " in *" $pub "*) ;; *) exit 1 ;; esac
    sed -n 3p "$in" | base64 -d > "$out"
fi
"""

FAKE_KEYGEN = r"""#!/bin/bash
if [ "$1" = "-y" ]; then sed -n 's/^# public key: //p' "$2"; exit 0; fi
[ "$1" = "-o" ] || exit 2
h=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
printf '# public key: age1test%s\nAGE-SECRET-KEY-TEST%s\n' "$h" "$h" > "$2"
"""

LOCALSH = """#!/bin/sh
shift
exec "$@"
"""


def _exe(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def env(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    path = os.environ["PATH"]
    if os.environ.get("KTP_TEST_FAKE_AGE") or shutil.which("age") is None or shutil.which("age-keygen") is None:
        _exe(bin_dir / "age", FAKE_AGE)
        _exe(bin_dir / "age-keygen", FAKE_KEYGEN)
    path = "%s:%s" % (bin_dir, path)
    base = dict(os.environ, PATH=path)
    keys = []
    for name in ("k1", "k2"):
        k = tmp_path / name
        subprocess.run(["age-keygen", "-o", str(k)], env=base, check=True, capture_output=True)
        k.chmod(0o600)
        keys.append(k)
    pubs = [subprocess.run(["age-keygen", "-y", str(k)], env=base, check=True,
                           capture_output=True, text=True).stdout.strip() for k in keys]
    localsh = _exe(tmp_path / "localsh", LOCALSH)
    base.update(
        KTP_CORPUS_AGE_RECIPIENTS=" ".join(pubs),
        KTP_OFFSITE_RSYNC_HOSTS="localhost",
        KTP_OFFSITE_RSYNC_RSH=str(localsh),
        KTP_OFFSITE_RSYNC_CORPUS_DIR=str(tmp_path / "archive"),
        KTP_OFFSITE_RSYNC_DIR="__demo__",
        KTP_OFFSITE_RSYNC_DB_DIR="__db__",
        KTP_CORPUS_SRC=str(tmp_path / "uploads"),
        KTP_WEAPON_CONTEXT_SRC=str(tmp_path / "weapon-context"),
        KTP_CORPUS_ENC_CACHE=str(tmp_path / "cache"),
    )
    return {"env": base, "key": keys[0], "root": tmp_path}


def _random(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    return path


SESSIONS = [998001, 998002, 999003, 999004, 999005]


def _populate(root: Path, sidecars=SESSIONS):
    for day in ("2026-09-01", "2026-09-02"):
        for i in range(3):
            _random(root / "uploads" / day / ("SYNTH_%d.zip" % i), 2048 + i)
    store = root / "weapon-context"
    (store / "tmp").mkdir(parents=True, exist_ok=True)
    for s in sidecars:
        _random(store / str(s // 1000) / ("%d.weapons.json" % s), 1500 + s % 7)
    _random(store / "tmp" / ("ab" * 16), 512)
    return store


def _offsite(ctx, *args):
    return subprocess.run(["bash", str(OFFSITE), *args], env=ctx["env"],
                          capture_output=True, text=True, timeout=120)


def _restore(ctx, dest: Path, *extra, key=None):
    return subprocess.run(
        ["bash", str(RESTORE), "--src", str(ctx["root"] / "archive"), "--dest", str(dest),
         "--key", str(key or ctx["key"]), *extra],
        env=ctx["env"], capture_output=True, text=True, timeout=120)


def _wc_objects(ctx):
    d = ctx["root"] / "archive" / "weapon-context" / "objects"
    return sorted(p.name for p in d.glob("*.age")) if d.is_dir() else []


def _tree(root: Path, skip=("tmp",)):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file() and p.relative_to(root).parts[0] not in skip}


def test_sidecars_ship_encrypted_under_their_own_prefix(env):
    _populate(env["root"])
    r = _offsite(env, "--commit")
    assert r.returncode == 0, r.stderr
    archive = env["root"] / "archive"
    assert len(_wc_objects(env)) == len(SESSIONS)
    assert (archive / "weapon-context" / "ktp-weapon-context-manifest.txt.age").is_file()
    assert len(list((archive / "weapon-context" / "manifests").glob("*.age"))) == 1
    # The two populations never mix: bundles only in day-dirs, sidecars only under the prefix.
    day_objects = [p for p in archive.glob("????-??-??/*.age")]
    assert len(day_objects) == 6
    assert not list(archive.glob("????-??-??/*weapons*"))
    assert not [p for p in archive.rglob("*") if ".weapons.json" in p.name]
    for obj in (archive / "weapon-context" / "objects").iterdir():
        assert obj.read_bytes().startswith(b"age-encryption.org")


def test_the_log_names_no_sidecar(env):
    store = _populate(env["root"])
    _random(store / "stray.bin", 64)
    r = _offsite(env, "--commit")
    assert r.returncode == 0, r.stderr
    out = r.stdout + r.stderr
    assert "1 file(s) under" in out and "NOT being copied" in out
    for s in SESSIONS:
        assert str(s) not in out
    assert "stray.bin" not in out


def test_a_rewrite_keeps_the_old_object_and_restores_the_new_one(env):
    store = _populate(env["root"])
    assert _offsite(env, "--commit").returncode == 0
    first = _wc_objects(env)
    target = store / "999" / "999004.weapons.json"
    tmp = store / "tmp" / "rewrite"
    tmp.write_bytes(os.urandom(4000))
    tmp.replace(target)
    r = _offsite(env, "--commit")
    assert r.returncode == 0, r.stderr
    second = _wc_objects(env)
    assert len(second) == len(first) + 1
    assert set(first) <= set(second), "an older version was removed from the far side"

    back = env["root"] / "wc-back"
    r = _restore(env, back, "--set", "weapon-context")
    assert r.returncode == 0, r.stderr
    assert _tree(back) == _tree(store), "the restore did not take the current versions"
    assert not (back / "tmp").exists()


def test_bundle_restore_is_unchanged_by_the_second_source(env):
    _populate(env["root"])
    assert _offsite(env, "--commit").returncode == 0
    back = env["root"] / "bundles-back"
    r = _restore(env, back)
    assert r.returncode == 0, r.stderr
    assert _tree(back) == _tree(env["root"] / "uploads")


def test_wrong_key_restores_no_sidecars(env, tmp_path):
    _populate(env["root"])
    assert _offsite(env, "--commit").returncode == 0
    other = tmp_path / "other.key"
    subprocess.run(["age-keygen", "-o", str(other)], env=env["env"], check=True, capture_output=True)
    other.chmod(0o600)
    r = _restore(env, tmp_path / "nokey", "--set", "weapon-context", key=other)
    assert r.returncode != 0


def test_an_empty_store_is_refused_and_nothing_ships(env):
    _populate(env["root"], sidecars=[])
    r = _offsite(env, "--commit")
    assert r.returncode != 0
    assert "matched no sidecars" in r.stderr
    assert not (env["root"] / "archive").exists()


def test_a_missing_store_is_refused(env):
    _populate(env["root"])
    shutil.rmtree(env["root"] / "weapon-context")
    r = _offsite(env, "--commit")
    assert r.returncode != 0
    assert "weapon-context store" in r.stderr


def test_dry_run_counts_sidecars_and_writes_nothing(env):
    _populate(env["root"])
    r = _offsite(env)
    assert r.returncode == 0, r.stderr
    assert "weapon-context: selected %d sidecar(s)" % len(SESSIONS) in r.stdout
    assert not (env["root"] / "archive").exists()
    assert not (env["root"] / "cache").exists()


def test_the_drill_round_trips_both_sources(env):
    e = dict(env["env"])
    for k in ("KTP_CORPUS_SRC", "KTP_WEAPON_CONTEXT_SRC", "KTP_CORPUS_ENC_CACHE",
              "KTP_OFFSITE_RSYNC_HOSTS", "KTP_OFFSITE_RSYNC_RSH", "KTP_OFFSITE_RSYNC_CORPUS_DIR"):
        e.pop(k)
    r = subprocess.run(["bash", str(DRILL), "--key", str(env["key"]), "--days", "2", "--per", "2", "--wc", "3"],
                       env=e, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "restored sidecars are byte-for-byte the CURRENT versions" in r.stdout
