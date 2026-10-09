"""Every Type=oneshot unit in this repo bounds its start, or says why it must not.

systemd disables TimeoutStartSec= for Type=oneshot by default, so a wedged run
stays in `activating`: the timer never re-triggers, `systemctl --failed` never
lists it, and OnFailure= needs an exit that never comes. All three legs read
green while the unit is dead -- docs/runbooks/ALERT_COVERAGE.md.

test_reports_unit_timeout.py pins one unit's value by literal path and so cannot
see a new one; this is the class check that was missing.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DROPIN_ROOT = ROOT / "scripts" / "systemd" / "dropins"
SKIP_PARTS = {".git", "node_modules", ".next", "bin", "obj", "__pycache__"}

# A unit that must run unbounded declares it here with its reason, so the
# exemption is reviewable instead of looking exactly like the omission.
OPT_OUT = re.compile(r"^[ \t]*[#;][ \t]*no-start-timeout:[ \t]*(\S.*)$", re.M)


def directives(text):
    """-> {section: {key: [values]}}. systemd allows indentation and ';' comments."""
    out = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section is None or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out.setdefault(section, {}).setdefault(key.strip(), []).append(value.strip())
    return out


def service(text, key):
    return directives(text).get("Service", {}).get(key, [])


def unit_files():
    return sorted(
        p
        for p in ROOT.rglob("*.service")
        if not SKIP_PARTS & set(p.relative_to(ROOT).parts)
    )


def dropin_sets_timeout(unit_path):
    """A drop-in can supply the directive, and a read of the unit file alone misses it."""
    folder = DROPIN_ROOT / (unit_path.name + ".d")
    if not folder.is_dir():
        return False
    return any(
        service(conf.read_text(encoding="utf-8"), "TimeoutStartSec")
        for conf in sorted(folder.glob("*.conf"))
    )


def rel(path):
    return path.relative_to(ROOT).as_posix()


def test_parser_is_section_scoped_and_ignores_comments():
    text = "[Unit]\nType=oneshot\n\n[Service]\n  Type=oneshot \n; note\n#TimeoutStartSec=1\nTimeoutStartSec=5min\n"
    assert service(text, "Type") == ["oneshot"]
    assert service(text, "TimeoutStartSec") == ["5min"]
    # A flat grep of the file would read the [Unit] Type= as the service's.
    assert directives(text)["Unit"]["Type"] == ["oneshot"]
    assert service("[Service]\n#TimeoutStartSec=1\n", "TimeoutStartSec") == []
    assert service("Type=oneshot\n", "Type") == []


def test_opt_out_marker_needs_a_reason():
    assert OPT_OUT.search("# no-start-timeout: it reboots the host mid-run\n")
    assert OPT_OUT.search("Type=oneshot\n  ; no-start-timeout: ditto, indented\n")
    assert not OPT_OUT.search("# no-start-timeout:\n")
    assert not OPT_OUT.search("# no-start-timeout:   \n")
    assert not OPT_OUT.search("# TimeoutStartSec is deliberately unset here\n")


def test_sweep_is_not_vacuous():
    units = unit_files()
    assert len(units) >= 10, [rel(p) for p in units]
    texts = {p: p.read_text(encoding="utf-8") for p in units}
    oneshots = [p for p, t in texts.items() if "oneshot" in service(t, "Type")]
    typed_other = [
        p
        for p, t in texts.items()
        if service(t, "Type") and "oneshot" not in service(t, "Type")
    ]
    # Both halves non-empty, or Type= is not being read the way this believes.
    assert oneshots, "no Type=oneshot unit found: the parser is not reading Type="
    assert typed_other, "every unit read as oneshot: the parser matches anything"
    assert any(service(texts[p], "TimeoutStartSec") for p in oneshots)
    # Exercises the opt-out branch against a real file, not only a fixture. Delete
    # this line with the last opt-out, never by widening it.
    assert any(OPT_OUT.search(texts[p]) for p in oneshots)


def test_no_unit_both_sets_a_timeout_and_claims_it_must_not():
    both = [
        rel(p)
        for p in unit_files()
        for t in [p.read_text(encoding="utf-8")]
        if service(t, "TimeoutStartSec") and OPT_OUT.search(t)
    ]
    assert not both, "contradictory: a start timeout plus a no-start-timeout claim: " + ", ".join(both)


def test_every_oneshot_bounds_its_start_or_says_why():
    offenders = []
    for path in unit_files():
        text = path.read_text(encoding="utf-8")
        if "oneshot" not in service(text, "Type"):
            continue
        if service(text, "TimeoutStartSec") or dropin_sets_timeout(path):
            continue
        if OPT_OUT.search(text):
            continue
        offenders.append(rel(path))
    assert not offenders, (
        "Type=oneshot with no TimeoutStartSec= and no '# no-start-timeout: <reason>': "
        + ", ".join(offenders)
    )
