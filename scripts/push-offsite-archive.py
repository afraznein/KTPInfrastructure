#!/usr/bin/env python3
"""Push a large archive to a PROVIDER-DIVERSE host, and verify it landed.

    python scripts/push-offsite-archive.py <host> <local-file> [--dest-dir /opt/ktp-demo-archive]

    python scripts/push-offsite-archive.py chicago-root C:/stage/Recovered-Matches-20260830.tar
    python scripts/push-offsite-archive.py denver-root  C:/stage/Recovered-Matches-20260830.tar

WHY THIS EXISTS
---------------
`Recovered Matches/` sat at 5.6 GB, unversioned, with exactly one copy and no
backup mechanism referencing it anywhere in the codebase -- found 2026-08-30 by
two independent sweeps. The 48 MB `ktp9-20260301-nogo-ax-all.dem.zip` inside it
is the sole copy of evidence three CLOSED S9 fixtures were verified against.
This project has already lost two days of demos to a silent failure once.

⛔ PROVIDER DIVERSITY IS THE POINT, AND IT CONSTRAINS THE DESTINATION.
Everything on `74.91.x` -- Atlanta, Dallas, New York **and the data server** --
is NFOservers, whose ToS states it keeps no backups and cannot compensate for
lost data. A second copy there survives a disk failure and does NOT survive an
account- or provider-level loss.

    provider-diverse targets:  chicago-root  (Linode, 172.238.x)
                               denver-root   (66.163.x)

⚠️ `sys_vendor` identifies the provider only on VMs. All four baremetals report
`Supermicro` -- the motherboard maker -- so that probe is useless there. Identify
a baremetal by IP block, not by asking the machine.

WHAT IT VERIFIES, AND WHY EACH CHECK IS HERE
--------------------------------------------
  * free space >= 110% of the file, BEFORE opening the stream
  * remote size == local size after the put
  * remote `sha256sum` == local sha256   <- the one that matters

**A transfer that returns without raising is not a verified copy.** SFTP can
report success on a truncated write, and the exit code of the enclosing shell
tells you nothing (`$?` after a pipeline reports the last command). The remote
hash is the only evidence the bytes arrived intact, so it is not optional and
not skippable.

It writes `SHA256SUMS` beside the artifact so the next person can re-verify
without this script.

CREDENTIALS
-----------
Imported from `ktp_hosts.py` at the project root -- never hardcoded. A stale
copy of a credential surfaces as `AuthenticationException`, which reads like a
host problem and once hid a broken deploy for ten weeks.

The local sha256 is read from `<file>.sha256` if present, else computed here.
"""
import argparse
import hashlib
import os
import sys
import time

sys.path.insert(0, os.environ.get("KTP_PROJECT_ROOT", r"N:/Nein_/KTP Git Projects"))
import ktp_hosts as k  # noqa: E402

PROVIDER_DIVERSE = {"chicago-root", "denver-root", "chicago", "denver"}


def local_sha256(path):
    side = path + ".sha256"
    if os.path.exists(side):
        with open(side) as fh:
            return fh.read().split()[0]
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host", help="ktp_hosts key, e.g. chicago-root")
    ap.add_argument("path", help="local file to push")
    ap.add_argument("--dest-dir", default="/opt/ktp-demo-archive")
    ap.add_argument("--allow-same-provider", action="store_true",
                    help="push to an NFO host anyway; this is NOT an offsite backup")
    a = ap.parse_args()

    if a.host not in PROVIDER_DIVERSE and not a.allow_same_provider:
        sys.exit("REFUSED: %r is not provider-diverse from the 74.91.x NFO block.\n"
                 "         Use chicago-root or denver-root, or pass --allow-same-provider\n"
                 "         if you understand this will not survive a provider-level loss."
                 % a.host)

    src = a.path
    name = os.path.basename(src)
    dest = a.dest_dir + "/" + name
    size = os.path.getsize(src)
    want = local_sha256(src)
    print("%s: pushing %s (%.2f GB), sha256 %s" % (a.host, name, size / 1073741824, want[:16]))

    c = k.connect(a.host, timeout=120)
    try:
        k.run(c, "mkdir -p %s && chmod 750 %s" % (a.dest_dir, a.dest_dir))

        free = k.run(c, "df -B1 --output=avail %s | tail -1" % a.dest_dir).strip()
        if not free.isdigit() or int(free) < size * 1.1:
            sys.exit("REFUSED: need %.1f GB free, host reports %r" % (size * 1.1 / 1073741824, free))

        sftp = c.open_sftp()
        sftp.get_channel().settimeout(600)
        t0 = time.time()
        mark = [0]

        def prog(done, total):
            pct = done * 100 // total
            if pct >= mark[0] + 10:
                mark[0] = pct
                el = max(time.time() - t0, 1)
                print("  %3d%%  %.2f GB  %.1f MB/s"
                      % (pct, done / 1073741824, done / 1048576 / el), flush=True)

        sftp.put(src, dest, callback=prog)
        sftp.close()
        print("  upload finished in %.1f min" % ((time.time() - t0) / 60))

        remote_size = k.run(c, "stat -c %%s %s" % dest).strip()
        if remote_size != str(size):
            sys.exit("** SIZE MISMATCH ** remote=%s local=%s" % (remote_size, size))
        print("  size matches (%s bytes)" % remote_size)

        print("  hashing on the remote ...", flush=True)
        got = k.run(c, "sha256sum %s" % dest, timeout=1800).split()[0]
        if got != want:
            sys.exit("** SHA MISMATCH ** remote=%s local=%s" % (got[:16], want[:16]))
        print("  sha256 matches: %s" % got[:16])

        k.run(c, 'grep -v " %s$" %s/SHA256SUMS 2>/dev/null > %s/.sums.tmp; '
                 'echo "%s  %s" >> %s/.sums.tmp; mv %s/.sums.tmp %s/SHA256SUMS'
                 % (name, a.dest_dir, a.dest_dir, want, name, a.dest_dir, a.dest_dir, a.dest_dir))
        print("VERIFIED IDENTICAL -> %s:%s" % (a.host, dest))
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
