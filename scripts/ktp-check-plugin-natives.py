#!/usr/bin/env python3
"""Does a plugin we are about to field call a native the fielded modules export?

WHY THIS EXISTS. `stage-wave.py` gates a wave on md5 pins, the attribution scan
and the version row. None of those read the plugin's NATIVES TABLE, and AMXX
resolves that table at LOAD, not at call: one unresolved name and
`CPluginMngr::CPlugin::Finalize` sets `ps_bad_load`, logs "Plugin uses an unknown
function (name ...) - check your modules.ini.", and the plugin does not run AT
ALL. A runtime `if` in front of the call buys nothing -- the reference sits in
the table whether the branch is ever taken -- and only a plugin registering
`set_native_filter` survives it, which among the in-tree plugins is plmenu alone.

So a plugin staged from a commit whose MODULE half was not staged with it kills
the whole plugin, on every instance at once, and does it quietly: the nightly
swap is `mv -f`, and `ktp-verify-post-swap.sh` looks for leftover `.new` files
rather than load status, so the first symptom is a stats path that went empty.

HOW IT DECIDES, AND WHY IT IS NOT A STRING GREP. A module's native names do come
out of its `.so` string table, but AMXX's CORE natives do not come out cleanly --
`copy` and `log_message` are in every plugin on this fleet and neither is
recoverable that way, so a bare "is this name in the strings" test reports two
false positives on a plugin that has run for weeks. The baseline is therefore the
LIVE artifact of the same basename: it is loading right now, so every native IT
references is resolvable here by demonstration. What this reports is the natives
the incoming build adds and the host cannot supply -- which is the only set that
can turn a working plugin into `ps_bad_load`.

That makes the live artifact a required control, not a convenience: an instance
with no live copy of the basename is reported as untrustworthy rather than clean.

This is a READ. It stages nothing, writes nothing, restarts nothing.

    ktp-check-plugin-natives.py --plugin build/stats_logging.amxx
    ktp-check-plugin-natives.py --staged stats_logging.amxx

Exit 0 every added native resolves, 1 some native does not, 2 the probe could
not be trusted. It fails CLOSED: an instance that cannot be read is a failure,
and a provider set too small to be a real module string table is reported as a
broken probe -- never as a finding.
"""
from __future__ import annotations

import argparse
import os
import posixpath
import struct
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from amxx_version import inflate  # noqa: E402  the XXMA container reader already here

# Below this the provider set cannot be a module string table, and calling every
# native unresolved would be a broken probe wearing a finding's clothes.
PROVIDER_FLOOR = 200

HOST_KEYS = ["atlanta", "chicago", "dallas", "denver", "newyork"]

PLUGIN_DIR = "serverfiles/dod/addons/ktpamx/plugins"
MODULE_ROOT = "serverfiles/dod/addons/ktpamx"


def required_natives(path):
    """Native names the compiled plugin asks AMXX to resolve at load."""
    out = []
    for image in inflate(path):
        # amx_header: size(4) magic(2) file_version(1) amx_version(1) flags(2)
        # defsize(2) then cod dat hea stp cip publics natives libraries pubvars
        # tags nametable -- so defsize is at 10, and natives/libraries at 36.
        defsize = struct.unpack_from("<h", image, 10)[0]
        natives, libraries = struct.unpack_from("<2i", image, 36)
        if defsize <= 0 or libraries < natives:
            continue
        for off in range(natives, libraries, defsize):
            _addr, nameofs = struct.unpack_from("<Ii", image, off)
            out.append(image[nameofs:image.index(b"\0", nameofs)].decode("latin-1"))
    return out


def _identifier_tokens(blob):
    keep = set()
    for line in blob.splitlines():
        line = line.strip()
        if line and (line[0].isalpha() or line[0] == "_") and all(
                c.isalnum() or c == "_" for c in line):
            keep.add(line)
    return keep


# One round trip per instance. The natives a plugin may resolve against are the
# ones in AMXX's core .so plus every module .so under the install, so `strings`
# over all of them is the provider set.
# `tr`, not `strings`. binutils is NOT on every host -- Dallas has no `strings`
# at all, which returned an EMPTY provider set and would have reported all five
# of its instances as broken had PROVIDER_FLOOR not caught it. `tr -c` splits on
# everything that cannot be in an identifier, needs only coreutils, and was
# measured to give the identical answer where both exist (8,953 tokens either
# way). The filter runs on the HOST because a module string table is megabytes.
_PROBE = (
    'base="$HOME/@INST@/' + MODULE_ROOT + '"; '
    'if [ ! -d "$base" ]; then echo KTPNG_NOINST; exit 0; fi; '
    'for f in $(find "$base" -name "*.so"); do tr -c "[:alnum:]_" "\\n" < "$f"; done '
    '  | grep -E "^[A-Za-z_][A-Za-z0-9_]{2,}$" | sort -u; '
    'echo "KTPNG_SOCOUNT=$(find "$base" -name "*.so" | wc -l)"'
)


def provided_natives(run, instance):
    out = run(_PROBE.replace("@INST@", instance))
    if "KTPNG_NOINST" in out:
        return set(), -1
    socount = -1
    for line in out.splitlines():
        if line.startswith("KTPNG_SOCOUNT="):
            socount = int(line.split("=", 1)[1])
    return _identifier_tokens(out), socount


def _fetch_natives(sftp, home, instance, name):
    """Required-natives set of a remote artifact, or None if it is not there.

    mkstemp, not a name built from the instance: the instance dirs repeat across
    hosts (every baremetal has a dod-27015), and the per-host workers run
    concurrently, so a composed name has two threads writing one path.
    """
    remote = posixpath.join(home, instance, PLUGIN_DIR, name)
    fd, local = tempfile.mkstemp(prefix="ktpng-", suffix="-" + os.path.basename(name))
    os.close(fd)
    try:
        try:
            sftp.get(remote, local)
        except IOError:
            return None
        return set(required_natives(local))
    finally:
        try:
            os.remove(local)
        except OSError:
            pass


def _synth_amxx(names, defsize=8):
    """A minimal XXMA container whose AMX natives table names exactly `names`.

    Hand-built rather than checked in as a fixture binary: the thing under test
    IS the offset arithmetic, and a committed .amxx would prove only that the
    reader still agrees with one build of one plugin.
    """
    hdr = 56  # size,magic,file_version,amx_version,flags,defsize + 11 int32
    nat = hdr
    libraries = nat + defsize * len(names)
    blob, offsets = b"", []
    for n in names:
        offsets.append(libraries + len(blob))
        blob += n.encode() + b"\0"
    image = bytearray(libraries + len(blob))
    struct.pack_into("<IHBBhh", image, 0, len(image), 0xF1E0, 8, 8, 0, defsize)
    struct.pack_into("<11i", image, 12,
                     hdr, hdr, hdr, hdr, 0, nat, nat, libraries, libraries,
                     libraries, libraries)
    for i, off in enumerate(offsets):
        struct.pack_into("<Ii", image, nat + i * defsize, 0, off)
    image[libraries:libraries + len(blob)] = blob
    body = zlib.compress(bytes(image))
    out = struct.pack("<IhB", 0x414D5858, 0x0300, 1)
    out += struct.pack("<Biiii", 4, len(body), len(image), len(image), 7 + 17)
    return out + body


def selftest():
    """Offline. Checks the reader's arithmetic and the decision, not the fleet."""
    fails = []

    def check(label, cond):
        print("  %-62s %s" % (label, "ok" if cond else "FAIL"))
        if not cond:
            fails.append(label)

    planted = ["dodx_get_shot_target4", "copy", "log_message", "register_plugin"]
    fd, path = tempfile.mkstemp(suffix=".amxx")
    os.close(fd)
    try:
        with open(path, "wb") as fh:
            fh.write(_synth_amxx(planted))
        got = required_natives(path)
        check("natives table reads back exactly what was planted", got == planted)
        check("a non-container yields no natives rather than raising",
              required_natives(__file__) == [])
    finally:
        os.remove(path)

    # The decision itself. `copy` and `log_message` are the real-world case: AMXX
    # core natives that a module string table does not yield, so without the live
    # baseline they read as unresolved on a plugin that has run for weeks.
    provided = {"dodx_get_shot_target3", "register_plugin"}
    baseline = {"copy", "log_message", "register_plugin", "dodx_get_shot_target3"}
    incoming = set(planted)
    check("only the ADDED unsupplied native is reported",
          sorted(incoming - provided - baseline) == ["dodx_get_shot_target4"])
    check("core natives absent from the module table are NOT reported",
          not ({"copy", "log_message"} & (incoming - provided - baseline)))
    check("an unchanged plugin reports nothing",
          not (baseline - provided - baseline))
    check("without the baseline the core natives WOULD be reported "
          "(so the baseline is load-bearing)",
          {"copy", "log_message"} <= (incoming - provided))

    check("identifier filter keeps names and drops punctuation lines",
          _identifier_tokens("dodx_get_shot_miss\nnot-an-ident\n_ok9\n12bad\n")
          == {"dodx_get_shot_miss", "_ok9"})
    check("PROVIDER_FLOOR is above any plausible empty result", PROVIDER_FLOOR > 0)

    print("\nselftest: %d check(s) failed" % len(fails))
    return 1 if fails else 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true",
                    help="Run the offline checks and exit (no fleet access).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--plugin", help="local .amxx to check before staging")
    src.add_argument("--staged", metavar="BASENAME",
                     help="check the already-staged <BASENAME>.new on each instance")
    ap.add_argument("--basename", help="live artifact to baseline against; defaults to "
                                      "the basename of --plugin or --staged")
    ap.add_argument("--hosts", default="all",
                    help="comma-separated host keys, or 'all' (default)")
    ap.add_argument("--hosts-dir", default=os.environ.get(
        "KTP_HOSTS_DIR", r"N:\Nein_\KTP Git Projects"),
        help="directory holding ktp_hosts.py")
    args = ap.parse_args()

    basename = args.basename or os.path.basename(args.plugin or args.staged)
    if basename.endswith(".new"):
        basename = basename[:-4]

    sys.path.insert(0, args.hosts_dir)
    import ktp_hosts  # noqa: E402

    hosts = HOST_KEYS if args.hosts == "all" else args.hosts.split(",")

    incoming_local = None
    if args.plugin:
        incoming_local = set(required_natives(args.plugin))
        if not incoming_local:
            print("FAIL: no natives table read out of %s -- not an .amxx?" % args.plugin)
            return 2
        print("incoming %s: %d natives referenced" % (args.plugin, len(incoming_local)))

    failures = checked = 0
    for host in hosts:
        conn = ktp_hosts.connect(host)
        home = ktp_hosts.run(conn, "echo $HOME").strip()
        instances = sorted(d for d in ktp_hosts.run(conn, "ls -1 $HOME | grep '^dod-'").split()
                           if d.startswith("dod-"))
        if not instances:
            print("FAIL %s: no dod-* instances enumerated -- probe untrustworthy" % host)
            return 2
        sftp = conn.open_sftp()
        try:
            for inst in instances:
                provided, socount = provided_natives(
                    lambda c, _c=conn: ktp_hosts.run(_c, c), inst)
                if socount < 1:
                    print("FAIL %s/%s: no modules found" % (host, inst))
                    failures += 1
                    continue
                if len(provided) < PROVIDER_FLOOR:
                    print("FAIL %s/%s: provider set only %d tokens from %d .so -- probe "
                          "untrustworthy, not a finding"
                          % (host, inst, len(provided), socount))
                    return 2

                # The control. This artifact is loading on this instance right now,
                # so every native it names is resolvable here by demonstration.
                baseline = _fetch_natives(sftp, home, inst, basename)
                if not baseline:
                    print("FAIL %s/%s: no live %s to baseline against -- probe "
                          "untrustworthy, not a finding" % (host, inst, basename))
                    return 2

                incoming = incoming_local
                if incoming is None:
                    incoming = _fetch_natives(sftp, home, inst, basename + ".new")
                    if incoming is None:
                        print("FAIL %s/%s: %s.new is not staged" % (host, inst, basename))
                        failures += 1
                        continue
                    if not incoming:
                        print("FAIL %s/%s: staged artifact yielded no natives table"
                              % (host, inst))
                        return 2

                missing = sorted(incoming - provided - baseline)
                checked += 1
                if missing:
                    failures += 1
                    print("UNRESOLVED %s/%s: %s" % (host, inst, ", ".join(missing)))
                else:
                    added = len(incoming - baseline)
                    print("ok %s/%s: %d natives, %d added over live, all resolve "
                          "(%d provided, %d .so)"
                          % (host, inst, len(incoming), added, len(provided), socount))
        finally:
            sftp.close()

    print("\n%d instances checked, %d with unresolved natives" % (checked, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
