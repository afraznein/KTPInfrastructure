"""Build + collect the artifact set a Lane B run tests.

## What "build" means here

Lane B tests a *branch*, so it needs the artifacts that branch produces, from
three repos at once:

| Artifact | Repo | Built? |
|---|---|---|
| `stats_logging.amxx` | KTPAMXX (+ the `.inc`) | compiled with amxxpc |
| `hlstats.pl` | KTPHLStatsX | no — Perl, copied |
| `ktp_schema.sql` + `migrate_*.sql` | KTPHLStatsX | no — copied |

Everything is extracted with `git show <ref>:<path>` rather than read from a
working tree. A working tree carries uncommitted edits, and "the tests passed"
must mean "the tests passed against this commit" or it is not a gate on
anything.

## The include-adjacency constraint

`stats_logging.sma` `#include`s `ktp_stats_capture.inc` by relative path, so the
two must land in the **same directory** before amxxpc runs. The production
Docker build hits this too — `build/plugins/Dockerfile` copies the stock
plugins as individual files, so `feat/stats-capture-include` had to add a
dedicated `COPY` line for the include. The deployment plan lists the mismatched
pair as a loud failure ("amxxpc fails: cannot read ktp_stats_capture.inc"), and
`stage()` reproduces the adjacency so it cannot happen here.

## Compile failures are fatal here, unlike in the Docker build

`build/plugins/Dockerfile`'s compile helper ends each invocation with
`|| echo "WARNING: $name may have had errors"`, so a broken plugin does not
fail the image build — it just does not produce a `.amxx`. That is survivable
for a build you inspect by hand, and useless for a test lane: the run would
proceed with a stale or absent plugin and report on whatever was already
staged. `compile_plugin()` raises.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class BuildError(RuntimeError):
    """A build or collection step failed. Always fatal — never degrade to
    'run anyway with whatever is on disk'."""


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise BuildError(f"git {' '.join(args)} in {repo} failed:\n{r.stderr.strip()}")
    return r.stdout


def resolve_ref(repo: Path, ref: str) -> str:
    """Full SHA for `ref`. Recorded in the manifest so a result can be traced
    back to exact commits rather than to a branch name that has since moved."""
    return _git(repo, "rev-parse", ref).strip()


def extract(repo: Path, ref: str, rel_path: str, dest: Path) -> Path:
    """`git show <ref>:<rel_path>` → dest. Binary-safe, no working-tree read."""
    r = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{rel_path}"],
        capture_output=True,
    )
    if r.returncode != 0:
        raise BuildError(
            f"{rel_path} not found at {ref} in {repo}:\n"
            f"{r.stderr.decode('utf-8', 'replace').strip()}"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.stdout)
    return dest


@dataclass
class ArtifactSet:
    """Everything one Lane B run needs, plus provenance for all of it."""

    build_dir: Path
    plugin_amxx: Path | None = None
    plugin_sma: Path | None = None
    plugin_inc: Path | None = None
    hlstats_pl: Path | None = None
    schema_sql: list[Path] = field(default_factory=list)
    seed_sql: list[Path] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    # -- collection --------------------------------------------------------

    @classmethod
    def collect(
        cls,
        build_dir: Path,
        *,
        amxx_repo: Path,
        amxx_ref: str,
        daemon_repo: Path,
        daemon_ref: str,
        schema_files: tuple[str, ...] = ("sql/ktp_schema.sql",),
        seed_files: tuple[str, ...] = (
            "sql/migrate_003_assist_action.sql",
            "sql/migrate_004_cap_break_action.sql",
        ),
    ) -> "ArtifactSet":
        """Pull every source artifact out of the two repos at the given refs.

        Does NOT compile — call `compile_plugin()` after, or supply a prebuilt
        `.amxx` via `use_prebuilt_plugin()`.
        """
        build_dir = Path(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        inst = cls(build_dir=build_dir)

        amxx_sha = resolve_ref(amxx_repo, amxx_ref)
        daemon_sha = resolve_ref(daemon_repo, daemon_ref)

        # Plugin sources land in ONE directory — see the include-adjacency
        # note in the module docstring.
        src = build_dir / "plugin-src"
        inst.plugin_sma = extract(
            amxx_repo, amxx_ref, "plugins/dod/stats_logging.sma", src / "stats_logging.sma")
        inst.plugin_inc = extract(
            amxx_repo, amxx_ref, "plugins/dod/ktp_stats_capture.inc",
            src / "ktp_stats_capture.inc")

        inst.hlstats_pl = extract(
            daemon_repo, daemon_ref, "scripts/hlstats.pl", build_dir / "hlstats.pl")

        for rel in schema_files:
            inst.schema_sql.append(
                extract(daemon_repo, daemon_ref, rel, build_dir / "sql" / Path(rel).name))
        for rel in seed_files:
            inst.seed_sql.append(
                extract(daemon_repo, daemon_ref, rel, build_dir / "sql" / Path(rel).name))

        inst.provenance = {
            "amxx": {"repo": str(amxx_repo), "ref": amxx_ref, "sha": amxx_sha},
            "daemon": {"repo": str(daemon_repo), "ref": daemon_ref, "sha": daemon_sha},
        }
        return inst

    # -- compiling ---------------------------------------------------------

    def compile_plugin(
        self,
        *,
        amxxpc: Path,
        include_dir: Path,
        timeout: float = 180.0,
    ) -> Path:
        """Compile stats_logging.sma → .amxx with amxxpc.

        `include_dir` is KTPAMXX's `plugins/include` — the KTP fork's, not
        stock AMXX 1.10's. The production build compiles these stock plugins
        against the fork's includes for exactly this reason, so using upstream
        includes here would test a plugin nobody ships.
        """
        if self.plugin_sma is None:
            raise BuildError("no plugin source collected; call collect() first")
        amxxpc = Path(amxxpc)
        include_dir = Path(include_dir)
        if not amxxpc.is_file():
            raise BuildError(f"amxxpc not found at {amxxpc}")
        if not include_dir.is_dir():
            raise BuildError(f"include dir not found at {include_dir}")

        out = self.build_dir / "stats_logging.amxx"
        src_dir = self.plugin_sma.parent

        # CRLF: these repos are CRLF in the working tree, and the Docker build
        # normalises before amxxpc (`sed "s/\r$//"`). Do the same so a compile
        # difference can never be a line-ending difference.
        #
        # Unconditional on purpose: what `git show` emits depends on the repo's
        # core.autocrlf and .gitattributes, so an extracted file can be LF even
        # though the working tree is CRLF. Guarding this on "looks like CRLF"
        # would just add a branch that is sometimes wrong.
        body = self.plugin_sma.read_bytes().replace(b"\r\n", b"\n")
        norm = src_dir / "stats_logging.sma"
        norm.write_bytes(body)
        inc = self.plugin_inc
        if inc is not None:
            inc.write_bytes(inc.read_bytes().replace(b"\r\n", b"\n"))

        # amxxpc must run FROM ITS OWN DIRECTORY. It dlopen()s `amxxpc32.so` by
        # bare name, so the loader searches the CWD — run it from anywhere else
        # and it dies with "compiler failed to instantiate: amxxpc32.so: cannot
        # open shared object file". Both existing build paths already do this:
        # build/plugins/Dockerfile does `cd /compiler && ./amxxpc`, and
        # smoke-callable.yml does `cd .../scripting && ./amxxpc /work/<src>`.
        # Hence the absolute source path and the relative `./amxxpc`.
        r = subprocess.run(
            [f"./{amxxpc.name}", str(norm),
             f"-i{include_dir}", f"-i{src_dir}", f"-o{out}"],
            cwd=str(amxxpc.parent), capture_output=True, text=True, timeout=timeout,
        )
        combined = (r.stdout or "") + (r.stderr or "")
        # amxxpc exits 0 on warnings, non-zero on errors — but it has also been
        # known to exit 0 having written nothing, so check the file too.
        if r.returncode != 0 or not out.is_file():
            raise BuildError(
                f"amxxpc failed (rc={r.returncode}) on stats_logging.sma:\n{combined[-4000:]}"
            )
        if "Error" in combined or "error:" in combined.lower():
            raise BuildError(f"amxxpc reported errors:\n{combined[-4000:]}")

        self.plugin_amxx = out
        self.provenance.setdefault("build", {})["amxxpc_output"] = combined[-4000:]
        self.provenance["build"]["warnings"] = combined.count("Warning")
        return out

    def use_prebuilt_plugin(self, path: Path) -> Path:
        """Adopt an externally-built `.amxx` (the Docker build, or a CI
        artifact from the GHCR base-image compile path).

        Records its md5 like any other artifact — the deployment plan insists
        deployments are verified by md5 rather than by console banner, and the
        same logic applies to knowing what a test run actually exercised.
        """
        path = Path(path)
        if not path.is_file():
            raise BuildError(f"prebuilt plugin not found: {path}")
        dest = self.build_dir / "stats_logging.amxx"
        shutil.copy2(path, dest)
        self.plugin_amxx = dest
        self.provenance.setdefault("build", {})["prebuilt_from"] = str(path)
        return dest

    # -- staging -----------------------------------------------------------

    def stage_plugin(self, tree, *, plugins_rel="dod/addons/ktpamx/plugins") -> Path:
        """Drop the compiled plugin into an EphemeralTree."""
        if self.plugin_amxx is None:
            raise BuildError("no compiled plugin; call compile_plugin() or use_prebuilt_plugin()")
        return tree.overlay_file(self.plugin_amxx, f"{plugins_rel}/stats_logging.amxx")

    # -- manifest ----------------------------------------------------------

    def manifest(self) -> dict:
        """Provenance + md5 of everything, so a Lane B result is traceable to
        exact commits and exact bytes."""
        files = {}
        for label, p in (
            ("stats_logging.amxx", self.plugin_amxx),
            ("hlstats.pl", self.hlstats_pl),
        ):
            if p is not None and p.is_file():
                files[label] = {"path": str(p), "md5": _md5(p), "bytes": p.stat().st_size}
        for p in self.schema_sql + self.seed_sql:
            files[p.name] = {"path": str(p), "md5": _md5(p), "bytes": p.stat().st_size}
        return {"provenance": self.provenance, "files": files}

    def write_manifest(self, path: Path | None = None) -> Path:
        path = Path(path) if path else (self.build_dir / "artifact-manifest.json")
        path.write_text(json.dumps(self.manifest(), indent=2), encoding="utf-8")
        return path
