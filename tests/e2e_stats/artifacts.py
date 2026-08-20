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

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class BuildError(RuntimeError):
    """A build or collection step failed. Always fatal — never degrade to
    'run anyway with whatever is on disk'."""


REQUIRED_BUNDLE_REPOSITORIES = frozenset(
    {"infrastructure", "matchhandler", "amxx", "hlstatsx"}
)
_FULL_GITHUB_SHA = re.compile(r"^[0-9a-f]{40}$")


DEFAULT_SCHEMA_FILES = (
    "sql/ktp_schema.sql",
    "sql/migrate_005_frag_context_columns.sql",
    "sql/migrate_006_damage_ledger.sql",
    "sql/migrate_007_break_context.sql",
    "sql/migrate_008_position_samples.sql",
    "sql/migrate_009_disable_connect_announcements.sql",
    "sql/migrate_010_flag_captures.sql",
    "sql/migrate_011_match_player_identity_width.sql",
    "sql/migrate_012_frag_context_correlation.sql",
    "sql/migrate_013_ktp_table_collation.sql",
    "sql/migrate_014_match_type_retention.sql",
    "sql/migrate_015_flag_state_events.sql",
    "sql/migrate_016_life_events.sql",
    "sql/migrate_017_capture_clocks_and_assists.sql",
)


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


def _validated_sha(value: str, *, label: str) -> str:
    sha = str(value).strip().lower()
    if not _FULL_GITHUB_SHA.fullmatch(sha):
        raise BuildError(
            f"{label} must be a resolved 40-character Git commit SHA, got {value!r}"
        )
    return sha


def record_bundle_provenance(
    manifest_path: Path,
    repositories: dict[str, dict[str, str]],
    *,
    workflow_context: dict[str, str] | None = None,
) -> dict:
    """Add the four-repository immutable bundle identity to a manifest.

    The artifact collector predates the cross-repository bundle and owns only
    the AMXX and daemon sources.  Infrastructure and MatchHandler are consumed
    directly from Actions checkouts, so the workflow records their checked-out
    ``HEAD`` values here after all four checkouts have completed.  Requiring the
    complete set prevents a report that looks exact while silently omitting one
    of the runtime inputs.
    """
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"cannot read artifact manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BuildError(f"artifact manifest {manifest_path} is not a JSON object")

    supplied = set(repositories)
    if supplied != REQUIRED_BUNDLE_REPOSITORIES:
        missing = sorted(REQUIRED_BUNDLE_REPOSITORIES - supplied)
        extra = sorted(supplied - REQUIRED_BUNDLE_REPOSITORIES)
        raise BuildError(
            "bundle provenance must contain exactly infrastructure, "
            f"matchhandler, amxx, and hlstatsx (missing={missing}, extra={extra})"
        )

    normalized: dict[str, dict[str, str]] = {}
    for name in sorted(REQUIRED_BUNDLE_REPOSITORIES):
        item = repositories[name]
        repository = str(item.get("repository", "")).strip()
        requested_ref = str(item.get("requested_ref", "")).strip()
        if not repository or not requested_ref:
            raise BuildError(
                f"bundle provenance for {name} needs repository and requested_ref"
            )
        normalized[name] = {
            "repository": repository,
            "requested_ref": requested_ref,
            "sha": _validated_sha(item.get("sha", ""), label=name),
        }

    # The artifact builder already resolved these two inputs independently.
    # Refuse to overwrite the manifest with a contradictory post-hoc claim.
    legacy = manifest.get("provenance") or {}
    for old_name, bundle_name in (("amxx", "amxx"), ("daemon", "hlstatsx")):
        old_sha = (legacy.get(old_name) or {}).get("sha")
        if old_sha and str(old_sha).lower() != normalized[bundle_name]["sha"]:
            raise BuildError(
                f"{bundle_name} checkout is {normalized[bundle_name]['sha']} but "
                f"the collected artifact came from {old_sha}"
            )

    context = dict(workflow_context or {})
    if context.get("event_sha"):
        context["event_sha"] = _validated_sha(
            context["event_sha"], label="workflow event_sha"
        )
    bundle = {"repositories": normalized, "workflow": context}
    manifest.setdefault("provenance", {})["bundle"] = bundle
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return bundle


def load_bundle_provenance(manifest_path: Path) -> dict:
    """Read and validate a complete immutable bundle from a saved manifest."""
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bundle = manifest["provenance"]["bundle"]
        repositories = bundle["repositories"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise BuildError(
            f"artifact manifest {manifest_path} has no valid bundle provenance: {exc}"
        ) from exc

    if set(repositories) != REQUIRED_BUNDLE_REPOSITORIES:
        raise BuildError(
            f"artifact manifest {manifest_path} does not identify all four repositories"
        )
    for name, item in repositories.items():
        _validated_sha(item.get("sha", ""), label=name)
        if not item.get("repository") or not item.get("requested_ref"):
            raise BuildError(f"artifact manifest has incomplete {name} provenance")
    return bundle


def render_bundle_provenance_markdown(bundle: dict) -> str:
    """Render full (not abbreviated) SHAs for the run summary artifact."""
    rows = [
        "## Exact bundle provenance",
        "",
        "| Component | Repository | Requested ref | Resolved commit |",
        "|---|---|---|---|",
    ]
    for name in ("infrastructure", "matchhandler", "amxx", "hlstatsx"):
        item = bundle["repositories"][name]
        rows.append(
            f"| {name} | `{item['repository']}` | `{item['requested_ref']}` "
            f"| `{item['sha']}` |"
        )
    workflow = bundle.get("workflow") or {}
    if workflow:
        rows += ["", "Workflow context:"]
        for key in ("workflow_ref", "event_sha", "run_url"):
            if workflow.get(key):
                rows.append(f"- {key}: `{workflow[key]}`")
    return "\n".join(rows) + "\n"


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
        include_plugin: bool = True,
        schema_files: tuple[str, ...] = DEFAULT_SCHEMA_FILES,
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

        amxx_sha = resolve_ref(amxx_repo, amxx_ref) if include_plugin else None
        daemon_sha = resolve_ref(daemon_repo, daemon_ref)

        # Plugin sources land in ONE directory — see the include-adjacency
        # note in the module docstring.
        if include_plugin:
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
        defines: tuple[str, ...] = (),
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
        argv = [f"./{amxxpc.name}", str(norm),
                f"-i{include_dir}", f"-i{src_dir}", f"-o{out}", *defines]
        r = subprocess.run(
            argv,
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
        self.provenance["build"]["defines"] = list(defines)
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


def _provenance_cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Record an immutable four-repository Lane B bundle"
    )
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--markdown", type=Path, default=None)
    ap.add_argument(
        "--repository",
        action="append",
        nargs=4,
        metavar=("NAME", "REPOSITORY", "REQUESTED_REF", "RESOLVED_SHA"),
        required=True,
    )
    ap.add_argument("--workflow-ref", default="")
    ap.add_argument("--event-sha", default="")
    ap.add_argument("--run-url", default="")
    args = ap.parse_args(argv)

    repositories = {
        name: {
            "repository": repository,
            "requested_ref": requested_ref,
            "sha": resolved_sha,
        }
        for name, repository, requested_ref, resolved_sha in args.repository
    }
    try:
        bundle = record_bundle_provenance(
            args.manifest,
            repositories,
            workflow_context={
                "workflow_ref": args.workflow_ref,
                "event_sha": args.event_sha,
                "run_url": args.run_url,
            },
        )
    except BuildError as exc:
        ap.error(str(exc))

    markdown = render_bundle_provenance_markdown(bundle)
    if args.markdown is not None:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(_provenance_cli())
