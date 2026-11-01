"""A map's analytics `map_config` must name the cfg `ktp_maps.ini` actually binds.

`config/analytics/map_flag_facts.json` gives every observed map a `config` name,
and `config/analytics/map_scoring.json` carries the tick model under that same
name. Nothing read the map list, so the two could disagree about which config a
map plays under and every match on it would be scored against the wrong tick
values -- silently, because both files stay internally consistent while they do
it. That is not hypothetical: a Saints mismatch was chased for over a week in
2026-10 and the suspicion ("b3e/b4e point at saints_b1, the servers exec
ktp_saints.cfg") was only ever settled by hand.

The nearest existing test (test_ktp_maps_ini_provenance) asserts that a bound
config FILE exists. A binding to a file that exists and a binding analytics
agrees with are different facts.

Scope, deliberately: the local profile's map list is a copy of the fleet's, not a
mirror (its own header says so), so a disagreement here is a question about this
repo's two analytics files, not a statement about what a server execs tonight.
"""

from __future__ import annotations

import json
import re

from scripts.map_scoring_facts import map_config_name

from .conftest import CONFIG_ROOT

MAPS_INI = CONFIG_ROOT / "local" / "ktp_maps.ini"
FLAG_FACTS = CONFIG_ROOT / "analytics" / "map_flag_facts.json"
SCORING = CONFIG_ROOT / "analytics" / "map_scoring.json"


def _bindings() -> dict[str, str]:
    """`{map name: config filename}` from ktp_maps.ini's sections."""
    text = MAPS_INI.read_text(encoding="utf-8")
    # Keys may appear in any order inside a section, so take the first
    # `config =` after each header rather than assuming it comes first.
    return dict(
        re.findall(r"^\[([^\]]+)\][^\[]*?^\s*config\s*=\s*(\S+)", text, re.MULTILINE | re.DOTALL)
    )


def _flag_facts() -> dict[str, dict]:
    return json.loads(FLAG_FACTS.read_text(encoding="utf-8"))["maps"]


def _scoring_names() -> set[str]:
    return {entry["map_config"] for entry in json.loads(SCORING.read_text(encoding="utf-8"))["maps"]}


def _scoring_by_name() -> dict[str, str | None]:
    """`{map name: map_config}` from the per-map view the report readers consume."""
    entries = json.loads(SCORING.read_text(encoding="utf-8"))["maps_by_name"]
    return {entry["map_name"]: entry.get("map_config") for entry in entries}


def test_both_sides_parse_and_overlap():
    # The control for every assertion below. A regex that stops matching, or a
    # `maps` key that moves, would empty one side and make the rest of this file
    # pass by measuring nothing.
    bindings = _bindings()
    facts = _flag_facts()
    assert bindings, "no `config =` bindings parsed out of ktp_maps.ini; the probe is broken"
    assert facts, "no maps parsed out of map_flag_facts.json; the probe is broken"
    assert _scoring_names(), "no map_config entries parsed out of map_scoring.json"
    assert set(bindings) & set(facts), (
        "no map appears in both ktp_maps.ini and map_flag_facts.json, so the "
        "cross-check below compares nothing"
    )


def test_analytics_config_matches_the_binding():
    bindings = _bindings()
    wrong = {}
    for name, entry in sorted(_flag_facts().items()):
        bound = bindings.get(name)
        if bound is None:
            continue  # not in this profile's map list; nothing to compare against
        expected = map_config_name(bound)
        if entry.get("config") != expected:
            wrong[name] = (entry.get("config"), expected, bound)
    assert not wrong, (
        "analytics names a different config than ktp_maps.ini binds, so these maps "
        "are scored against the wrong tick model: "
        + "; ".join(
            f"{m}: map_flag_facts says {got!r}, {b} implies {exp!r}"
            for m, (got, exp, b) in wrong.items()
        )
    )


def test_a_bound_map_has_a_config_in_analytics():
    # `config: null` is right for a map the fleet plays with no KTP config (the aim
    # maps). It is wrong for one the map list binds: analytics would then score it
    # against the defaults while the server execs real tick values.
    bindings = _bindings()
    unconfigured = sorted(
        name
        for name, entry in _flag_facts().items()
        if name in bindings and not entry.get("config")
    )
    assert not unconfigured, (
        "ktp_maps.ini binds a config for these maps but map_flag_facts.json leaves "
        f"`config` null, so nothing carries their tick model: {unconfigured}"
    )


def test_every_named_config_has_a_tick_model():
    # One direction only. A map_scoring entry no map points at is a config file
    # that exists, not dead data -- the generator's own docstring says so, and
    # pruning one deletes a fact.
    named = {entry["config"] for entry in _flag_facts().values() if entry.get("config")}
    orphans = sorted(named - _scoring_names())
    assert not orphans, (
        "map_flag_facts.json names configs with no map_scoring.json entry, so their "
        f"tick model is missing: {orphans}"
    )


def test_the_served_per_map_view_agrees_with_the_binding():
    # maps_by_name is generated from map_flag_facts.json, so it agrees with it by
    # construction -- but only as of the last generator run. A binding change plus a
    # regenerated flag_facts and a stale commit of this view passes every check
    # above while the readers keep serving the old config name.
    bindings = _bindings()
    served = _scoring_by_name()
    assert served, "no maps_by_name entries parsed; the probe is broken, not the file"
    wrong = {
        name: (got, map_config_name(bindings[name]))
        for name, got in sorted(served.items())
        if name in bindings and got != map_config_name(bindings[name])
    }
    assert not wrong, (
        "map_scoring.json's maps_by_name names a different config than ktp_maps.ini "
        "binds, so the served tick model is the wrong one: "
        + "; ".join(f"{m}: serves {got!r}, binding implies {exp!r}" for m, (got, exp) in wrong.items())
    )
