"""Per-stream capture authorization: one stream's loss must not withhold another.

Pure Python -- no database -- so it runs in the required config-tests check.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import match_analytics as analytics  # noqa: E402

CAPABILITIES = (
    "frag_context,damage,position,assist,life,break,flag_state,flag_position,"
    "objective_attempt,team_membership,grenade_entity,position_state,"
    "map_revision,sequence,health"
)
REVISION = "a" * 64


def _schema23_position_evidence():
    manifests = [{
        "half": 1, "schema_version": 23, "capabilities": CAPABILITIES,
        "position_interval": 2.0, "map_revision_algorithm": "sha256",
        "map_revision_sha256": REVISION,
    }]
    health = [{
        "half": 1, "event_type": event_type,
        "attempted": 1 if event_type == "position" else 0,
        "enqueued": 1 if event_type == "position" else 0,
        "dropped": 0, "emitted": 1 if event_type == "position" else 0,
        "daemon_received": 1 if event_type == "position" else 0,
        "daemon_accepted": 1 if event_type == "position" else 0,
        "daemon_rejected": 0, "correlation_failure_count": 0,
        "sequence_gap_count": 0, "duplicate_or_reordered_count": 0,
    } for event_type in analytics.CAPTURE_EVENT_TYPES]
    positions = [{
        "half": 1, "is_alive": 1, "is_spectator": 0,
        "map_revision_sha256": REVISION,
    }]
    return manifests, health, positions


def _two_half_evidence():
    """Manifest + health for a clean two-half schema-23 capture."""
    manifests, health, _ = _schema23_position_evidence()
    manifests.append({**manifests[0], "half": 2})
    health += [{**row, "half": 2} for row in health]
    return manifests, health


def _authorize_two_halves(manifests, health):
    return analytics.evaluate_capture_authorization(
        {1, 2}, manifests, health, require_activation=False)


def _break_stream(health, event_type, half, field, value):
    row = next(r for r in health
               if r["event_type"] == event_type and r["half"] == half)
    row[field] = value


def test_one_streams_loss_no_longer_withholds_a_sibling_stream():
    """The coupling this split removes.

    Against the pre-change gate every one of these assertions fails: a frag
    correlation failure marked the whole match unauthorized, so the objective
    and grenade streams -- whose own counters reconcile exactly -- published
    nothing.
    """
    manifests, health = _two_half_evidence()
    _break_stream(health, "frag", 1, "correlation_failure_count", 7)
    result = _authorize_two_halves(manifests, health)

    assert result["authorized"] is False
    assert analytics.capture_stream_authorized(result, "frag") is False
    assert analytics.capture_stream_authorized(result, "objective_attempt") is True
    assert analytics.capture_stream_authorized(result, "grenade_entity") is True
    assert "frag" not in result["authorized_streams"]
    assert "objective_attempt" in result["authorized_streams"]
    assert result["match_errors"] == []


def test_a_withheld_stream_carries_the_reason_it_was_withheld():
    """Silent absence is the defect; a withheld stream must say why."""
    manifests, health = _two_half_evidence()
    _break_stream(health, "objective_attempt", 2, "dropped", 3)
    result = _authorize_two_halves(manifests, health)

    state = analytics.capture_stream_status(result, "objective_attempt")
    assert state["authorized"] is False
    assert state["status"] == "withheld"
    assert "half 2 objective_attempt counters do not reconcile" in state["reason"]

    block = analytics.lifecycle_block(
        result, "objective_attempt", analytics.objective_attempt_summary, [])
    assert block["status"] == "withheld"
    assert block["stream"] == "objective_attempt"
    assert "objective_attempt counters do not reconcile" in block["withheld_reason"]
    assert "Withheld" in analytics.lifecycle_line(block, "counts")


def test_a_stream_authorizes_across_halves_not_per_half():
    """Half 1 clean, half 2 lossy: the stream is withheld for the match.

    Consumers query a stream for the whole match, so publishing one half would
    be a partial aggregate with nothing marking it partial.
    """
    manifests, health = _two_half_evidence()
    _break_stream(health, "grenade_entity", 2, "daemon_rejected", 1)
    _break_stream(health, "grenade_entity", 2, "daemon_accepted", 0)
    result = _authorize_two_halves(manifests, health)

    assert analytics.capture_stream_authorized(result, "grenade_entity") is False
    assert analytics.capture_stream_authorized(result, "objective_attempt") is True


def test_a_sequence_gap_is_charged_to_the_stream_that_lost_the_line():
    """Before schema 24 the gap is half-wide: the daemon stamps one value into
    every stream's row. Charging it per stream would re-couple the match."""
    manifests, health = _two_half_evidence()
    for row in health:
        if row["half"] == 1:
            row["sequence_gap_count"] = 1
    _break_stream(health, "position", 1, "daemon_received", 0)
    _break_stream(health, "position", 1, "daemon_accepted", 0)
    result = _authorize_two_halves(manifests, health)

    assert result["match_errors"] == []
    assert analytics.capture_stream_authorized(result, "position") is False
    assert analytics.capture_stream_authorized(result, "objective_attempt") is True


def test_an_unaccounted_sequence_gap_still_fails_the_whole_match():
    """A gap no stream's emitted/received shortfall explains is unattributable."""
    manifests, health = _two_half_evidence()
    for row in health:
        if row["half"] == 1:
            row["sequence_gap_count"] = 4
    result = _authorize_two_halves(manifests, health)

    assert result["authorized_streams"] == []
    assert any("no stream" in error for error in result["match_errors"])


def test_a_repeated_health_row_cannot_absorb_an_unaccounted_gap():
    """A duplicated row would double-count its stream's shortfall and launder a
    residual into every sibling's publish decision."""
    manifests, health = _two_half_evidence()
    for row in health:
        if row["half"] == 1:
            row["sequence_gap_count"] = 2
    _break_stream(health, "frag", 1, "daemon_received", 0)
    _break_stream(health, "frag", 1, "daemon_accepted", 0)
    health.append(dict(next(r for r in health
                            if r["half"] == 1 and r["event_type"] == "frag")))
    result = _authorize_two_halves(manifests, health)

    assert result["authorized_streams"] == []
    assert any("no stream" in error for error in result["match_errors"])


def test_a_withheld_streams_reason_never_names_a_sibling():
    manifests, health = _two_half_evidence()
    health[:] = [row for row in health
                 if not (row["half"] == 1 and row["event_type"] in ("frag", "assist"))]
    result = _authorize_two_halves(manifests, health)

    reason = analytics.capture_stream_status(result, "frag")["reason"]
    assert "frag" in reason
    assert "assist" not in reason


def test_a_match_with_no_capture_at_all_reads_as_not_captured():
    """Nothing failed to authorize; there was never anything to authorize."""
    capture = analytics.evaluate_capture_authorization({1}, [], [])
    block = analytics.lifecycle_block(
        capture, "objective_attempt", analytics.objective_attempt_summary, [])

    assert block["status"] == "not_captured"
    assert analytics.lifecycle_line(block, "COUNTS").startswith("**Not captured**")
    assert "did not authorize" not in analytics.lifecycle_line(block, "COUNTS")


def test_a_duplicate_or_reordered_line_still_fails_the_whole_match():
    manifests, health = _two_half_evidence()
    for row in health:
        if row["half"] == 2:
            row["duplicate_or_reordered_count"] = 1
    result = _authorize_two_halves(manifests, health)

    assert result["authorized_streams"] == []
    assert any("duplicate or reordered" in e for e in result["match_errors"])


def test_any_loss_still_fails_its_own_stream_no_tolerance():
    """Per-stream is not a loss tolerance: one dropped line still fails."""
    manifests, health = _two_half_evidence()
    _break_stream(health, "objective_attempt", 1, "dropped", 1)
    _break_stream(health, "objective_attempt", 1, "enqueued", 0)
    _break_stream(health, "objective_attempt", 1, "emitted", 0)
    _break_stream(health, "objective_attempt", 1, "daemon_received", 0)
    _break_stream(health, "objective_attempt", 1, "daemon_accepted", 0)
    result = _authorize_two_halves(manifests, health)

    assert analytics.capture_stream_authorized(result, "objective_attempt") is False


def test_a_broken_match_precondition_still_withholds_every_stream():
    """Half-set and manifest evidence bind every stream at once."""
    manifests, health = _two_half_evidence()
    manifests[1]["schema_version"] = 21
    result = _authorize_two_halves(manifests, health)

    assert result["authorized"] is False
    assert result["match_errors"]
    assert result["authorized_streams"] == []
    assert analytics.capture_stream_status(
        result, "objective_attempt")["reason"]


def test_an_unknown_health_type_withholds_every_stream():
    """A producer/daemon disagreement is not attributable to one stream."""
    manifests, health = _two_half_evidence()
    health.append({**health[0], "event_type": "not_a_real_stream"})
    result = _authorize_two_halves(manifests, health)

    assert result["authorized_streams"] == []
    assert any("not_a_real_stream" in e for e in result["match_errors"])


def test_position_provenance_rides_on_the_position_stream_alone():
    """A frag failure used to withhold position provenance too."""
    manifests, health, positions = _schema23_position_evidence()
    _break_stream(health, "frag", 1, "correlation_failure_count", 2)
    result = analytics.evaluate_position_provenance(
        {1}, manifests, health, positions)

    assert result["authorized"] is True


def _pre_change_verdict(observed, manifests, health):
    """The match-level rule exactly as it stood before the per-stream split.

    Frozen by definition -- it is history, not a second implementation to keep
    in step. It exists so the "consumers that read `authorized` are unaffected"
    claim is held by a test rather than by an argument.
    """
    if not manifests and not health:
        return False
    errors = []
    manifest_halves = [int(row.get("half") or 0) for row in manifests]
    health_halves = {int(row.get("half") or 0) for row in health}
    if set(manifest_halves) != observed or len(manifest_halves) != len(observed):
        errors.append(1)
    if health_halves != observed:
        errors.append(1)
    for row in manifests:
        capabilities = {item.strip() for item
                        in str(row.get("capabilities") or "").split(",") if item.strip()}
        if (int(row.get("schema_version") or 0) not in {22, 23, 24, 25}
                or abs(float(row.get("position_interval") or 0) - 2.0) > 0.01
                or not {"objective_attempt", "grenade_entity"}.issubset(capabilities)):
            errors.append(1)
    required = set(analytics.CAPTURE_EVENT_TYPES)
    optional = set(analytics.CAPTURE_EVENT_TYPES_OPTIONAL)
    for half in sorted(observed):
        rows = [row for row in health if int(row.get("half") or 0) == half]
        types = [str(row.get("event_type") or "") for row in rows]
        seen = set(types)
        if required - seen or seen - required - optional or len(types) != len(seen):
            errors.append(1)
        for row in rows:
            counters = {key: int(row.get(key) or 0) for key in (
                "attempted", "enqueued", "dropped", "emitted", "daemon_received",
                "daemon_accepted", "daemon_rejected", "correlation_failure_count",
                "sequence_gap_count", "duplicate_or_reordered_count")}
            if (min(counters.values()) < 0
                    or counters["attempted"] != counters["enqueued"] + counters["dropped"]
                    or counters["enqueued"] != counters["emitted"]
                    or counters["emitted"] != counters["daemon_received"]
                    or counters["daemon_accepted"] + counters["daemon_rejected"]
                    != counters["daemon_received"]
                    or any(counters[key] for key in (
                        "dropped", "daemon_rejected", "correlation_failure_count",
                        "sequence_gap_count", "duplicate_or_reordered_count"))):
                errors.append(1)
    return not errors and bool(observed)


def _random_evidence(rng):
    halves = rng.choice([{1}, {1, 2}])
    manifests = [{
        "half": half, "schema_version": rng.choice([22, 23, 24, 25, 21]),
        "capabilities": CAPABILITIES,
        "position_interval": rng.choice([2.0, 2.0, 2.0, 1.0]),
    } for half in sorted(halves)]
    if rng.random() < 0.1:
        manifests = manifests[:1]
    health = []
    for half in sorted(halves):
        gap = rng.choice([0, 0, 0, 0, 1, 3])
        duplicates = rng.choice([0, 0, 0, 0, 1])
        for event_type in analytics.CAPTURE_EVENT_TYPES:
            emitted = rng.randint(0, 5)
            lost = rng.choice([0, 0, 0, 0, 1]) if emitted else 0
            dropped = rng.choice([0, 0, 0, 0, 1])
            rejected = rng.choice([0, 0, 0, 0, 1]) if emitted - lost else 0
            health.append({
                "half": half, "event_type": event_type,
                "attempted": emitted + dropped, "enqueued": emitted,
                "dropped": dropped, "emitted": emitted,
                "daemon_received": emitted - lost,
                "daemon_accepted": emitted - lost - rejected,
                "daemon_rejected": rejected,
                "correlation_failure_count": rng.choice([0, 0, 0, 0, 1]),
                "sequence_gap_count": gap,
                "duplicate_or_reordered_count": duplicates,
            })
        if rng.random() < 0.05:
            health.pop()
    return halves, manifests, health


def test_match_level_authorized_still_means_what_it_meant():
    """Consumers reading `authorized` must see no change, in either direction."""
    rng = random.Random(7)
    for _ in range(4000):
        halves, manifests, health = _random_evidence(rng)
        result = analytics.evaluate_capture_authorization(halves, manifests, health)
        assert result["authorized"] is _pre_change_verdict(halves, manifests, health)


def _with_schema(version):
    manifests, health, positions = _schema23_position_evidence()
    manifests[0]["schema_version"] = version
    return manifests, health, positions


def test_schema_25_authorizes_capture_and_position_like_24():
    for version in (24, 25, 26):
        manifests, health, positions = _with_schema(version)
        capture = analytics.evaluate_capture_authorization({1}, manifests, health)
        position = analytics.evaluate_position_provenance(
            {1}, manifests, health, positions)
        assert capture["authorized"] is True, (version, capture["errors"])
        assert position["authorized"] is True, (version, position["errors"])


def test_schemas_outside_the_accepted_set_are_still_refused():
    for version in (20, 27):
        manifests, health, positions = _with_schema(version)
        assert analytics.evaluate_capture_authorization(
            {1}, manifests, health)["authorized"] is False
        assert analytics.evaluate_position_provenance(
            {1}, manifests, health, positions)["authorized"] is False


# Counts in the shape the schema-24 daemon writes: every stream on its own
# sequence, so a half's rows carry different gap counters.
_PER_STREAM_COUNTS = {
    "life": 770, "damage": 655, "position": 5763, "frag": 334, "assist": 42,
    "break": 6, "flag_state": 135, "flag_position": 15,
    "objective_attempt": 64, "team_membership": 0, "grenade_entity": 588,
    "shot": 2913, "score": 117, "duel": 9, "player_state": 649,
    "grenade_throw": 287,
}


def _per_stream_half(half, schema=24):
    manifest = {
        "half": half, "schema_version": schema, "capabilities": CAPABILITIES,
        "position_interval": 2.0,
    }
    rows = []
    for event_type, emitted in _PER_STREAM_COUNTS.items():
        rows.append({
            "half": half, "event_type": event_type, "attempted": emitted,
            "enqueued": emitted, "dropped": 0, "emitted": emitted,
            "daemon_received": emitted, "daemon_accepted": emitted,
            "daemon_rejected": 0, "correlation_failure_count": 0,
            "sequence_gap_count": 0, "duplicate_or_reordered_count": 0,
        })
    return manifest, rows


def _per_stream_evidence(schema=24):
    m1, h1 = _per_stream_half(1, schema)
    m2, h2 = _per_stream_half(2, schema)
    return [m1, m2], h1 + h2


def _lose(health, event_type, half, lost, gap):
    row = next(r for r in health
               if r["event_type"] == event_type and r["half"] == half)
    row["daemon_received"] -= lost
    row["daemon_accepted"] -= lost
    row["sequence_gap_count"] = gap


def test_per_stream_gaps_explained_by_their_own_loss_withhold_only_those_streams():
    """Measured shape: damage lost 9 and shows 8 gaps (one lost at the tail),
    player_state lost 16 and shows 13."""
    manifests, health = _per_stream_evidence()
    _lose(health, "damage", 2, lost=9, gap=8)
    _lose(health, "player_state", 2, lost=16, gap=13)
    result = _authorize_two_halves(manifests, health)

    assert result["match_errors"] == []
    assert analytics.capture_stream_authorized(result, "damage") is False
    assert analytics.capture_stream_authorized(result, "player_state") is False
    assert analytics.capture_stream_authorized(result, "frag") is True
    assert analytics.capture_stream_authorized(result, "objective_attempt") is True


def test_a_stream_whose_gap_its_own_counters_cannot_explain_is_withheld():
    """Measured shape: a context re-activated mid-half, so life's sequence
    resumed past numbers its reset `emitted` never counted. emitted equals
    received, so nothing else marks the stream; the old half-wide residual let
    it publish whenever a sibling's larger shortfall absorbed the gap."""
    manifests, health = _per_stream_evidence()
    _lose(health, "life", 1, lost=0, gap=9)
    _lose(health, "position", 1, lost=23, gap=11)
    result = _authorize_two_halves(manifests, health)

    state = analytics.capture_stream_status(result, "life")
    assert state["authorized"] is False
    assert result["stream_authorization"]["life"]["scope"] == "stream"
    assert "half 1 life has 9 sequence-gap line(s)" in state["reason"]
    assert analytics.capture_stream_authorized(result, "frag") is True


def test_one_streams_unexplained_gap_no_longer_withholds_every_stream():
    """Per-stream counters make a gap attributable, so it must not be charged
    to the match the way an unattributable half-wide gap was."""
    manifests, health = _per_stream_evidence()
    for event_type, gap in (("life", 9), ("position", 36), ("flag_state", 10),
                            ("flag_position", 10), ("player_state", 1)):
        _lose(health, event_type, 1, lost=0, gap=gap)
    result = _authorize_two_halves(manifests, health)

    assert result["match_errors"] == []
    assert result["authorized"] is False
    for event_type in ("life", "position", "flag_state", "flag_position",
                       "player_state"):
        assert analytics.capture_stream_authorized(result, event_type) is False
    for event_type in ("frag", "damage", "objective_attempt", "grenade_entity"):
        assert analytics.capture_stream_authorized(result, event_type) is True


def test_a_per_stream_duplicate_withholds_only_its_own_stream():
    manifests, health = _per_stream_evidence()
    row = next(r for r in health
               if r["event_type"] == "shot" and r["half"] == 2)
    row["duplicate_or_reordered_count"] = 2
    result = _authorize_two_halves(manifests, health)

    assert result["match_errors"] == []
    assert analytics.capture_stream_authorized(result, "shot") is False
    assert "duplicate or reordered" in analytics.capture_stream_status(
        result, "shot")["reason"]
    assert analytics.capture_stream_authorized(result, "frag") is True


def test_schema_25_reads_gaps_per_stream_like_24():
    manifests, health = _per_stream_evidence(schema=25)
    _lose(health, "duel", 2, lost=0, gap=2)
    result = _authorize_two_halves(manifests, health)

    assert result["match_errors"] == []
    assert analytics.capture_stream_authorized(result, "duel") is False
    assert analytics.capture_stream_authorized(result, "frag") is True


def test_a_clean_per_stream_capture_authorizes_every_stream():
    manifests, health = _per_stream_evidence()
    result = _authorize_two_halves(manifests, health)

    assert result["authorized"] is True, result["errors"]


def _withheld_reason(health_edits):
    manifests, health = _two_half_evidence()
    for field, value in health_edits.items():
        _break_stream(health, "damage", 1, field, value)
    result = _authorize_two_halves(manifests, health)
    return analytics.capture_stream_status(result, "damage")["reason"]


def test_a_withheld_reason_names_loss_between_producer_and_daemon():
    """Lines lost after the producer emitted them are not a producer drop or a
    daemon rejection, and the reason has to say which one it was."""
    reason = _withheld_reason({
        "attempted": 100, "enqueued": 100, "emitted": 100,
        "daemon_received": 97, "daemon_accepted": 97,
    })

    assert "half 1 damage counters do not reconcile" in reason
    assert "3 of 100 emitted never reached the daemon" in reason
    assert "dropped" not in reason
    assert "rejected" not in reason


def test_a_withheld_reason_names_a_daemon_rejection():
    reason = _withheld_reason({
        "attempted": 10, "enqueued": 10, "emitted": 10, "daemon_received": 10,
        "daemon_accepted": 8, "daemon_rejected": 2,
        "correlation_failure_count": 2,
    })

    assert "daemon rejected 2" in reason
    assert "2 correlation failure(s)" in reason
    assert "never reached the daemon" not in reason


def test_a_withheld_reason_names_a_producer_drop():
    reason = _withheld_reason({
        "attempted": 10, "enqueued": 9, "dropped": 1, "emitted": 9,
        "daemon_received": 9, "daemon_accepted": 9,
    })

    assert "producer dropped 1" in reason
    assert "never reached the daemon" not in reason


def test_a_reconciled_stream_still_authorizes():
    """Control: naming causes must not invent one for a clean stream."""
    manifests, health = _two_half_evidence()
    result = _authorize_two_halves(manifests, health)

    assert analytics.capture_stream_authorized(result, "damage") is True
    assert result["errors"] == []
