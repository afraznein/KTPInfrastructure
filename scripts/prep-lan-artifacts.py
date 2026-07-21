#!/usr/bin/env python3
"""
prep-lan-artifacts.py — assemble everything the LAN box needs to come up matching
the live production fleet, into one staging folder you carry to the venue.

It pulls the CURRENT game-server files off a live fleet host and the stats/HLTV/
FastDL setup off the data server, so the LAN box runs the same versions the fleet
runs today (not whatever the repo baseline happens to be).

Produces under OUT_DIR (default: ./lan-prep-<date>):
  artifacts/engine/{hlds_linux,engine_i486.so}
  artifacts/ktpamx/{dlls,modules,plugins}/...     (current KTP stack + HUD)
  artifacts/libsteam_api.so
  bundles/hltv-bundle.tar.gz          (data server: package-hltv-bundle.sh)
  bundles/hlstatsx-bundle.tar.gz      (data server: package-hlstatsx-bundle.sh)
  bundles/fastdl-bundle.tar.gz        (data server: package-fastdl-bundle.sh --maps-only)
  bundles/dod-base.tar.gz             (local test tree, via WSL)
  sql/schema-prod.sql                 (data server: mysqldump --no-data hlstatsx)
  sql/hlstats-servers.sql             (generated: the 5 competitive server rows)
  MANIFEST.txt                        (md5s + how to point lan-deploy.conf at it)

Then in lan-deploy.conf:
  ARTIFACTS_PATH=<OUT_DIR>/artifacts
  LIBSTEAM_API_PATH=<OUT_DIR>/artifacts/libsteam_api.so
  HLTV_BINARIES_PATH / HLSTATSX_SOURCE_PATH / FASTDL_FILES_PATH / DOD_BASE_PATH
      -> the extracted bundle dirs (see MANIFEST.txt)

Credentials come from the environment (never hardcoded, never printed):
  KTP_FLEET_SSH_PASSWORD    dodserver on the fleet host   (--fleet-host)
  KTP_DATA_SSH_PASSWORD     root on the data server       (--data-host)
  KTP_HLSTATSX_DB_PASSWORD  MySQL 'hlstatsx' user (for the --no-data schema dump)

Usage:
  export KTP_FLEET_SSH_PASSWORD=... KTP_DATA_SSH_PASSWORD=... KTP_HLSTATSX_DB_PASSWORD=...
  python3 prep-lan-artifacts.py --fleet-host 74.91.121.9 --data-host 74.91.112.242
  python3 prep-lan-artifacts.py --only artifacts        # run a single stage
  python3 prep-lan-artifacts.py --lan-ip 192.168.1.50   # bake the venue IP into the server rows now
  python3 prep-lan-artifacts.py --dry-run               # print the plan, touch nothing
"""

import argparse
import hashlib
import os
import posixpath
import subprocess
import sys

try:
    import paramiko
except ImportError:
    sys.exit("paramiko required: pip install paramiko  (or run under WSL where it's installed)")

STAGES = ["artifacts", "bundles", "schema", "serverrows", "dodbase", "manifest"]

# Where each piece lives on a live fleet host, relative to the instance serverfiles.
FLEET_INSTANCE = "dod-27015/serverfiles"
ARTIFACT_TAR_PATHS = [
    "engine_i486.so",
    "hlds_linux",
    "libsteam_api.so",
    "dod/addons/ktpamx/dlls",
    "dod/addons/ktpamx/modules",
    "dod/addons/ktpamx/plugins",
]


def log(msg):
    print(f"[prep] {msg}", flush=True)


def connect(host, user, password):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, username=user, password=password, timeout=30)
    return c


def run(ssh, cmd, check=True, timeout=600):
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    o, e = out.read().decode(errors="replace"), err.read().decode(errors="replace")
    if check and rc != 0:
        raise RuntimeError(f"remote command failed (rc={rc}): {cmd}\n{e.strip()}")
    return o, e, rc


def download(ssh, remote, local):
    os.makedirs(os.path.dirname(local), exist_ok=True)
    sftp = ssh.open_sftp()
    try:
        sftp.get(remote, local)
    finally:
        sftp.close()


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def need_env(name):
    v = os.environ.get(name)
    if not v:
        sys.exit(f"missing environment variable {name} — see the header of this script")
    return v


# ---------------------------------------------------------------------------

def stage_artifacts(args, out):
    """Pull the current game stack off a live fleet host, reshaped for clone-ktp-stack."""
    art = os.path.join(out, "artifacts")
    if args.dry_run:
        log(f"[dry] tar+pull {ARTIFACT_TAR_PATHS} from {args.fleet_host}:{FLEET_INSTANCE} -> {art}")
        return
    pw = need_env("KTP_FLEET_SSH_PASSWORD")
    ssh = connect(args.fleet_host, "dodserver", pw)
    try:
        tar_paths = " ".join(ARTIFACT_TAR_PATHS)
        remote_tar = "/tmp/lan-artifacts-raw.tar.gz"
        log("bundling the current stack on the fleet host...")
        run(ssh, f"cd ~/{FLEET_INSTANCE} && tar czf {remote_tar} {tar_paths}")
        local_tar = os.path.join(out, "_artifacts-raw.tar.gz")
        log("downloading...")
        download(ssh, remote_tar, local_tar)
        run(ssh, f"rm -f {remote_tar}", check=False)
    finally:
        ssh.close()

    # Extract + reshape into the layout clone-ktp-stack expects.
    raw = os.path.join(out, "_raw")
    os.makedirs(raw, exist_ok=True)
    subprocess.run(["tar", "xzf", local_tar, "-C", raw], check=True)
    layout = {
        "engine_i486.so": "engine/engine_i486.so",
        "hlds_linux": "engine/hlds_linux",
        "libsteam_api.so": "libsteam_api.so",
        "dod/addons/ktpamx/dlls": "ktpamx/dlls",
        "dod/addons/ktpamx/modules": "ktpamx/modules",
        "dod/addons/ktpamx/plugins": "plugins",
    }
    for src, dst in layout.items():
        s, d = os.path.join(raw, src), os.path.join(art, dst)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        subprocess.run(["cp", "-r", s, d], check=True)
    subprocess.run(["rm", "-rf", raw, local_tar], check=True)
    # Sanity: the files clone-ktp-stack REQUIRES + the HUD plugin.
    required = [
        "engine/hlds_linux", "engine/engine_i486.so", "libsteam_api.so",
        "ktpamx/dlls/ktpamx_i386.so",
        "ktpamx/modules/dodx_ktp_i386.so", "ktpamx/modules/reapi_ktp_i386.so",
        "ktpamx/modules/amxxcurl_ktp_i386.so",
        "plugins/KTPHudObserver.amxx",
    ]
    missing = [r for r in required if not os.path.isfile(os.path.join(art, r))]
    if missing:
        sys.exit(f"assembled artifacts are INCOMPLETE — missing: {missing}\n"
                 f"(the HUD or a module isn't on the fleet host you pulled from)")
    log(f"artifacts assembled at {art} ({len(os.listdir(os.path.join(art, 'plugins')))} plugins)")


def _run_data_packager(ssh, script_name, remote_out, extra=""):
    """Run one package-*.sh on the data server; assumes the repo scripts are present there."""
    # The packagers live with the KTPInfrastructure checkout on the data server.
    # Try a couple of common locations; fall back to a clear error.
    find = ("for d in /root/KTPInfrastructure/scripts /opt/KTPInfrastructure/scripts "
            "/usr/local/bin; do [ -f \"$d/%s\" ] && echo \"$d/%s\" && break; done" % (script_name, script_name))
    path, _, _ = run(ssh, find, check=False)
    path = path.strip()
    if not path:
        raise RuntimeError(f"{script_name} not found on the data server — copy the "
                           f"KTPInfrastructure/scripts there, or run the packagers by hand.")
    run(ssh, f"bash {path} {extra} {remote_out}", timeout=1800)


def stage_bundles(args, out):
    jobs = [
        ("package-hltv-bundle.sh", "/tmp/hltv-bundle.tar.gz", "", "hltv-bundle.tar.gz"),
        ("package-hlstatsx-bundle.sh", "/tmp/hlstatsx-bundle.tar.gz", "", "hlstatsx-bundle.tar.gz"),
        ("package-fastdl-bundle.sh", "/tmp/fastdl-bundle.tar.gz", "--maps-only", "fastdl-bundle.tar.gz"),
    ]
    if args.dry_run:
        for s, ro, extra, _ in jobs:
            log(f"[dry] {args.data_host}: {s} {extra} -> {ro} -> download")
        return
    pw = need_env("KTP_DATA_SSH_PASSWORD")
    ssh = connect(args.data_host, "root", pw)
    try:
        for script, remote_out, extra, local_name in jobs:
            log(f"building {local_name} on the data server (this can take a while)...")
            _run_data_packager(ssh, script, remote_out, extra)
            local = os.path.join(out, "bundles", local_name)
            download(ssh, remote_out, local)
            run(ssh, f"rm -f {remote_out}", check=False)
            log(f"  {local_name}: {md5(local)}")
    finally:
        ssh.close()


def stage_schema(args, out):
    """Dump the CURRENT prod stats schema (structure only). This is the authoritative
    schema for the LAN — it carries every match_id column the daemon writes to, which
    the repo's install.sql + ktp_schema.sql do not."""
    if args.dry_run:
        log(f"[dry] {args.data_host}: mysqldump --no-data hlstatsx -> sql/schema-prod.sql")
        return
    pw = need_env("KTP_DATA_SSH_PASSWORD")
    dbpw = need_env("KTP_HLSTATSX_DB_PASSWORD")
    ssh = connect(args.data_host, "root", pw)
    try:
        remote = "/tmp/schema-prod.sql"
        # Password is passed via MYSQL_PWD in the remote env so it isn't in the arg list.
        run(ssh, f"MYSQL_PWD='{dbpw}' mysqldump --no-data --skip-add-drop-table "
                 f"-u hlstatsx hlstatsx > {remote}")
        local = os.path.join(out, "sql", "schema-prod.sql")
        download(ssh, remote, local)
        run(ssh, f"rm -f {remote}", check=False)
        ntables = sum(1 for line in open(local, encoding="utf-8", errors="replace")
                      if line.startswith("CREATE TABLE"))
        log(f"schema-prod.sql: {ntables} tables, {md5(local)}")
    finally:
        ssh.close()


def stage_serverrows(args, out):
    """Generate the 5 competitive hlstats_Servers rows. Without these (and with
    AllowOnlyConfigServers on) HLStatsX drops every packet from the LAN servers."""
    ip = args.lan_ip or "<LAN_IP>"
    rcon = "<RCON_PASSWORD>"
    lines = [
        "-- Register the 5 competitive LAN servers with HLStatsX.",
        "-- Replace <LAN_IP> and <RCON_PASSWORD> if not already filled in, then:",
        "--   MYSQL_PWD=... mysql -u hlstatsx hlstatsx < hlstats-servers.sql",
        "",
    ]
    for i in range(5):
        port = 27015 + i
        name = f"KTP LAN {i + 1}"
        lines.append(
            "INSERT INTO hlstats_Servers (address, port, name, game, publicaddress, rcon_password) "
            f"VALUES ('{ip}', {port}, '{name}', 'dod', '{ip}:{port}', '{rcon}')"
            "\n  ON DUPLICATE KEY UPDATE name=VALUES(name), rcon_password=VALUES(rcon_password);"
        )
    content = "\n".join(lines) + "\n"
    if args.dry_run:
        log(f"[dry] write sql/hlstats-servers.sql (5 rows, ip={ip})")
        return
    path = os.path.join(out, "sql", "hlstats-servers.sql")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    log(f"hlstats-servers.sql written (ip={ip})")


def stage_dodbase(args, out):
    """Build the dod/ content bundle (maps/models/overviews) from the local test tree.
    Run this script under WSL — package-dod-base.sh is bash and paths are native there."""
    local_out = os.path.join(out, "bundles", "dod-base.tar.gz")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "package-dod-base.sh")
    if args.dry_run:
        log(f"[dry] bash {script} '' {local_out}")
        return
    os.makedirs(os.path.dirname(local_out), exist_ok=True)
    r = subprocess.run(["bash", script, "", local_out], capture_output=True, text=True)
    if r.returncode != 0:
        log(f"dod-base build failed (non-fatal) — run it by hand under WSL:\n{r.stderr[-500:]}")
        return
    if os.path.isfile(local_out):
        log(f"dod-base.tar.gz: {md5(local_out)}")


def stage_manifest(args, out):
    if args.dry_run:
        log("[dry] write MANIFEST.txt")
        return
    lines = ["KTP LAN prep — carry this whole folder to the venue.", ""]
    art = os.path.join(out, "artifacts")
    if os.path.isdir(art):
        lines.append("ARTIFACTS (md5):")
        for root, _, files in os.walk(art):
            for fn in sorted(files):
                p = os.path.join(root, fn)
                lines.append(f"  {os.path.relpath(p, art)} = {md5(p)}")
        lines.append("")
    for sub in ("bundles", "sql"):
        d = os.path.join(out, sub)
        if os.path.isdir(d):
            lines.append(f"{sub.upper()}:")
            for fn in sorted(os.listdir(d)):
                p = os.path.join(d, fn)
                if os.path.isfile(p):
                    lines.append(f"  {fn} = {md5(p)}")
            lines.append("")
    lines += [
        "lan-deploy.conf pointers:",
        f"  ARTIFACTS_PATH={os.path.abspath(art)}",
        f"  LIBSTEAM_API_PATH={os.path.abspath(os.path.join(art, 'libsteam_api.so'))}",
        "  (extract each bundle and point HLTV_BINARIES_PATH / HLSTATSX_SOURCE_PATH /",
        "   FASTDL_FILES_PATH / DOD_BASE_PATH at the extracted dirs)",
        "",
        "On the LAN data server, load the stats schema + server rows:",
        "  MYSQL_PWD=<pw> mysql -u hlstatsx hlstatsx < sql/schema-prod.sql",
        "  MYSQL_PWD=<pw> mysql -u hlstatsx hlstatsx < sql/hlstats-servers.sql   # after LAN_IP is filled in",
    ]
    with open(os.path.join(out, "MANIFEST.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    log(f"MANIFEST.txt written under {out}")


STAGE_FN = {
    "artifacts": stage_artifacts, "bundles": stage_bundles, "schema": stage_schema,
    "serverrows": stage_serverrows, "dodbase": stage_dodbase, "manifest": stage_manifest,
}


def main():
    ap = argparse.ArgumentParser(description="Assemble the LAN artifact/bundle set from live prod.")
    ap.add_argument("--fleet-host", default="74.91.121.9", help="live fleet host to pull the game stack from")
    ap.add_argument("--data-host", default="74.91.112.242", help="production data server (bundles + schema)")
    ap.add_argument("--out", default=None, help="output staging dir (default ./lan-prep-<date>)")
    ap.add_argument("--lan-ip", default=None, help="venue LAN IP to bake into the server rows (optional)")
    ap.add_argument("--only", choices=STAGES, help="run a single stage")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    args = ap.parse_args()

    if not args.out:
        from datetime import date
        args.out = os.path.abspath(f"./lan-prep-{date.today().isoformat()}")
    if not args.dry_run:
        os.makedirs(args.out, exist_ok=True)
    log(f"staging into {args.out}")

    stages = [args.only] if args.only else STAGES
    for st in stages:
        log(f"=== stage: {st} ===")
        try:
            STAGE_FN[st](args, args.out)
        except Exception as e:
            log(f"stage '{st}' failed: {e}")
            if not args.dry_run:
                sys.exit(1)
    log("done.")


if __name__ == "__main__":
    main()
