"""Per-run throwaway serverfiles tree for the stats-capture bot lane.

`help.md` and TEST_INFRASTRUCTURE_PLAN are explicit that the Tier 2 runner's
`serverfiles/` must match the live fleet, that drift is tripwired, and that
re-sync is DELIBERATELY MANUAL. A bot `.so` dropped into that tree is exactly
the drift the tripwire exists to catch, and repairing it is hand work.

So this module never writes into the source tree. It builds a per-run copy,
overlays the bot kit + test artifacts there, and deletes it on teardown.

## The hardlink hazard (read before editing)

A full copy of a serverfiles tree is ~2 GB. Hardlinking is ~100x faster and is
what makes a per-run tree affordable at all. But a hardlink is the *same
inode*: opening a hardlinked path with mode "w" writes THROUGH to the source
file. That would silently corrupt the fleet-matching tree — the precise
outcome this module exists to prevent, arrived at by the back door.

Every write therefore goes through `safe_write_*`, which **unlinks first** so
the write lands on a fresh inode. Do not add a bare `open(path, "w")` or
`shutil.copy()` onto a path inside the tree; use the helpers.

As a backstop, `EphemeralTree` records a hash of every source file it is about
to shadow and re-checks them on teardown (`verify_source_untouched`). If a
future edit reintroduces a write-through, the run fails loudly with the path
that got clobbered instead of leaving a quietly-drifted tree behind.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class TreeIntegrityError(RuntimeError):
    """A write leaked through to the source tree. The source tree may now
    differ from the fleet — treat as an infrastructure incident, not a test
    failure."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink if possible, else copy. Falls back on cross-device links."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


@dataclass
class EphemeralTree:
    """A throwaway serverfiles tree built from a pristine source.

    Usage:
        with EphemeralTree.build(source) as tree:
            tree.overlay_file(bot_so, "dod/addons/marinebot/marinebot.so")
            tree.write_text("dod/test_server.cfg", cfg_body)
            boot(tree.path, ...)
    """

    path: Path
    source: Path
    copy_mode: str
    _shadow_hashes: dict[str, str] = field(default_factory=dict)
    _keep: bool = False

    # -- construction ------------------------------------------------------

    @classmethod
    def build(
        cls,
        source: Path,
        *,
        copy_mode: str = "hardlink",
        parent: Path | None = None,
        keep: bool = False,
    ) -> "EphemeralTree":
        """Materialise a copy of `source`.

        copy_mode:
          "hardlink" — fast; safe only because every write here unlinks first.
          "full"     — slow, ~2 GB, immune to write-through by construction.
                       Use when debugging anything that smells like tree
                       corruption.

        `parent` must be on the same filesystem as `source` for hardlink mode
        to actually link (else it silently degrades to copying, which is
        correct but slow). Defaults to a tempdir beside the source.
        """
        source = Path(source).resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"source serverfiles tree not found: {source}")
        if not (source / "hlds_linux").exists():
            raise FileNotFoundError(
                f"{source} has no hlds_linux — refusing to treat it as a serverfiles tree"
            )
        if copy_mode not in ("hardlink", "full"):
            raise ValueError(f"copy_mode must be 'hardlink' or 'full', got {copy_mode!r}")

        parent = Path(parent) if parent else source.parent
        parent.mkdir(parents=True, exist_ok=True)
        dest = Path(tempfile.mkdtemp(prefix="ktp-e2e-tree-", dir=str(parent)))

        # Refuse the degenerate case outright rather than discovering it by
        # corrupting things.
        if dest.resolve() == source or source in dest.resolve().parents:
            raise ValueError("ephemeral tree must not live inside the source tree")

        copy_fn = _link_or_copy if copy_mode == "hardlink" else shutil.copy2
        shutil.copytree(
            source,
            dest,
            copy_function=copy_fn,
            dirs_exist_ok=True,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                # Prior runs' logs and rollback copies are large and useless
                # here. Excluding them keeps even a full copy tolerable.
                "*.log", "core.*", "stack-bak-*", "plugin-bak-*", "*.dem",
            ),
        )
        return cls(path=dest, source=source, copy_mode=copy_mode, _keep=keep)

    # -- writes (the only sanctioned mutation path) ------------------------

    def _prepare(self, rel: str) -> Path:
        """Resolve `rel` inside the tree, record the source hash if we are
        about to shadow a real file, and unlink so the write cannot follow a
        hardlink back to the source."""
        target = (self.path / rel).resolve()
        if self.path not in target.parents and target != self.path:
            raise ValueError(f"refusing to write outside the ephemeral tree: {rel}")

        src_equivalent = self.source / rel
        if src_equivalent.is_file() and rel not in self._shadow_hashes:
            self._shadow_hashes[rel] = _sha256(src_equivalent)

        target.parent.mkdir(parents=True, exist_ok=True)
        # THE load-bearing line. Without it, a hardlinked path is the source
        # file and "w" edits the fleet-matching tree in place.
        if target.exists() or target.is_symlink():
            target.unlink()
        return target

    def write_text(self, rel: str, body: str, *, encoding: str = "utf-8") -> Path:
        target = self._prepare(rel)
        target.write_text(body, encoding=encoding)
        return target

    def write_bytes(self, rel: str, body: bytes) -> Path:
        target = self._prepare(rel)
        target.write_bytes(body)
        return target

    def overlay_file(self, src: Path, rel: str) -> Path:
        """Copy an external file (bot .so, test-mode .amxx) into the tree."""
        src = Path(src)
        if not src.is_file():
            raise FileNotFoundError(f"overlay source missing: {src}")
        target = self._prepare(rel)
        shutil.copy2(src, target)
        return target

    def overlay_dir(self, src: Path, rel: str) -> Path:
        """Copy an external directory (waypoints) into the tree."""
        src = Path(src)
        if not src.is_dir():
            raise FileNotFoundError(f"overlay source dir missing: {src}")
        target = (self.path / rel).resolve()
        if self.path not in target.parents:
            raise ValueError(f"refusing to write outside the ephemeral tree: {rel}")
        # Record hashes for any source files this will shadow.
        src_equivalent = self.source / rel
        if src_equivalent.is_dir():
            for f in src_equivalent.rglob("*"):
                if f.is_file():
                    key = str(f.relative_to(self.source)).replace(os.sep, "/")
                    self._shadow_hashes.setdefault(key, _sha256(f))
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target, symlinks=True)
        return target

    # -- integrity + teardown ---------------------------------------------

    def verify_source_untouched(self) -> None:
        """Re-hash every source file this tree shadowed. Raises on mismatch.

        Cheap (a handful of files) and the only thing standing between a
        future careless write and a silently drifted fleet-matching tree.
        """
        drifted = []
        for rel, expected in self._shadow_hashes.items():
            src_file = self.source / rel
            if not src_file.is_file():
                drifted.append(f"{rel} (vanished from source)")
                continue
            if _sha256(src_file) != expected:
                drifted.append(rel)
        if drifted:
            raise TreeIntegrityError(
                "writes leaked through to the SOURCE serverfiles tree at "
                f"{self.source} — it no longer matches what it did at run start:\n  "
                + "\n  ".join(drifted)
                + "\nThe fleet-drift tripwire will fire on this. Re-sync the runner "
                "tree before trusting any further Tier 2 result."
            )

    def cleanup(self) -> None:
        self.verify_source_untouched()
        if self._keep:
            return
        shutil.rmtree(self.path, ignore_errors=True)

    def cleanup_ignoring_integrity(self) -> None:
        """Remove the tree without re-running the integrity check.

        Only for callers that have ALREADY observed and handled a leak (the
        guard's own tests). Production paths must use `cleanup()` — swallowing
        the check is how a drifted source tree gets missed.
        """
        if self._keep:
            return
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> "EphemeralTree":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Integrity check runs even on the exception path — a corrupted source
        # tree is worse news than whatever the test was failing on, so it must
        # not be masked by an earlier error.
        try:
            self.verify_source_untouched()
        finally:
            if not self._keep:
                shutil.rmtree(self.path, ignore_errors=True)
