"""ktp-ac-retention.sh: the two horizons that have no OFF switch now refuse a zero.

`0` means opposite things to the two families of sweep in this script, and before this
only one family was guarded:

  - `UPLOAD_RETENTION_DAYS` and `NET_IDENTITY_RETENTION_DAYS` are each wrapped in their
    own test at the sweep, so 0 is a documented hold that retains everything.
  - `WEAPON_RETENTION_DAYS` and `TOKEN_RETENTION_DAYS` go straight into
    `INTERVAL ${n} DAY`. `NOW() - INTERVAL 0 DAY` is `NOW()`, so a zero deletes every row
    up to now -- successfully, reporting a count that reads like any ordinary night.

A negative is worse than a zero and is the case a `-gt 0`-shaped fix is written for
without anyone saying so: `NOW() - INTERVAL -5 DAY` is five days in the FUTURE, so it
takes rows that have not aged at all.

⚠ The hazard was the ADJACENCY, not any ruled value. The ruled `WEAPON_RETENTION_DAYS=36500`
sits in `scripts/cron.d/ktp-ac-retention` directly beneath a comment block saying 0 is
inert -- true of uploads, false of weapons. A comment cannot refuse, which is why this is a
guard and a test rather than a clearer warning.

🔑 WHY THE REFUSAL IS UP FRONT rather than at each sweep. The sweeps run in order and
sweep 2 is a DELETE: a guard that fires where the value is used has already let an earlier
sweep write. The exit is taken before any statement reaches the fake, and
`test_a_refusal_runs_no_statement_at_all` is the leg that proves it rather than assuming it.

⛔ What this does NOT prove: that MySQL parses anything, or anything about the live tables
or the installed copy on the data server. The repo change is not a deploy. The mutation
tests at the bottom are what show these assertions can fail at all.
"""


import pytest

from tests.unit.test_ac_retention_net_identity import SCRIPT, run_script

NO_OFF = "has no OFF switch"
NOT_AN_INT = "is not an integer"


# ── non-vacuity: the script must RUN under this harness with sane horizons ──

def test_the_script_completes_with_positive_horizons(tmp_path):
    """Every refusal below asserts something only because this passes."""
    r = run_script(tmp_path, env={"WEAPON_RETENTION_DAYS": "365",
                                  "TOKEN_RETENTION_DAYS": "22"})
    assert r.rc == 0, r.err
    assert NO_OFF not in r.err and NOT_AN_INT not in r.err


def test_the_defaults_are_positive(tmp_path):
    """The shipped defaults must not themselves trip the guard."""
    r = run_script(tmp_path)
    assert r.rc == 0, r.err


# ── the two that must refuse ───────────────────────────────────────────

@pytest.mark.parametrize("var", ["WEAPON_RETENTION_DAYS", "TOKEN_RETENTION_DAYS"])
@pytest.mark.parametrize("value", ["0", "-1", "-5"])
def test_a_non_positive_horizon_is_refused(tmp_path, var, value):
    r = run_script(tmp_path, env={var: value})
    assert r.rc == 2, f"rc={r.rc} out={r.out} err={r.err}"
    assert NO_OFF in r.err
    assert var in r.err


@pytest.mark.parametrize("var", ["WEAPON_RETENTION_DAYS", "TOKEN_RETENTION_DAYS",
                                 "UPLOAD_RETENTION_DAYS", "NET_IDENTITY_RETENTION_DAYS"])
def test_a_non_integer_horizon_names_its_own_variable(tmp_path, var):
    """Without this the value reaches `[ "$x" -le 0 ]` and dies as a bare bash
    "integer expression expected" that names no variable."""
    r = run_script(tmp_path, env={var: "thirty"})
    assert r.rc == 2, f"rc={r.rc} out={r.out} err={r.err}"
    assert NOT_AN_INT in r.err
    assert var in r.err


def test_a_refusal_runs_no_statement_at_all(tmp_path):
    """The whole point of validating before the first sweep: a refusal that fires
    after sweep 2 has deleted is not a refusal."""
    r = run_script(tmp_path, env={"WEAPON_RETENTION_DAYS": "0"})
    assert r.rc == 2
    assert r.sql.strip() == "", f"statements reached the database: {r.sql!r}"


# ── the two that must KEEP accepting 0, which is their documented hold ──

@pytest.mark.parametrize("var", ["UPLOAD_RETENTION_DAYS", "NET_IDENTITY_RETENTION_DAYS"])
def test_zero_is_still_a_hold_for_the_guarded_pair(tmp_path, var):
    """⛔ The asymmetry is deliberate and must survive this change. Tightening these
    two to positive as well would turn both documented holds into a nightly failure --
    and `UPLOAD_RETENTION_DAYS` DEFAULTS to 0, so it would break every host."""
    r = run_script(tmp_path, env={var: "0"})
    assert r.rc == 0, r.err
    assert NO_OFF not in r.err


def test_the_guarded_pair_still_report_being_off(tmp_path):
    """Not merely tolerated -- they still take their own off branch and say so."""
    r = run_script(tmp_path, env={"NET_IDENTITY_RETENTION_DAYS": "0"})
    assert r.rc == 0, r.err
    assert "NET_IDENTITY_RETENTION_DAYS=0" in r.out


# ── mutations: each must redden, or the leg above passes for free ──────
#
# ⚠ A mutation that does not LAND runs the unmutated script and passes for free. Each
# helper asserts the replacement actually changed the text before the script is run.

def _mutate(old, new):
    text = SCRIPT.read_text(encoding="utf-8")
    assert old in text, f"mutation anchor absent, so the mutation would not land: {old!r}"
    mutated = text.replace(old, new, 1)
    assert mutated != text, "mutation did not change the script"
    return mutated


def test_mutation_dropped_weapon_guard_reddens(tmp_path):
    script = _mutate('require_positive_days WEAPON_RETENTION_DAYS "${WEAPON_RETENTION_DAYS}"',
                     ': # guard removed')
    r = run_script(tmp_path, env={"WEAPON_RETENTION_DAYS": "0"}, script_text=script)
    assert r.rc != 2 or NO_OFF not in r.err, \
        "the guard was removed and the script still refused -- the leg is not measuring it"


def test_mutation_dropped_token_guard_reddens(tmp_path):
    script = _mutate('require_positive_days TOKEN_RETENTION_DAYS "${TOKEN_RETENTION_DAYS}"',
                     ': # guard removed')
    r = run_script(tmp_path, env={"TOKEN_RETENTION_DAYS": "0"}, script_text=script)
    assert r.rc != 2 or NO_OFF not in r.err


def test_mutation_guard_comparison_inverted_reddens(tmp_path):
    """`-le 0` flipped to `-lt 0` lets a zero through, which is the exact defect."""
    script = _mutate('if [ "$2" -le 0 ]; then', 'if [ "$2" -lt 0 ]; then')
    r = run_script(tmp_path, env={"WEAPON_RETENTION_DAYS": "0"}, script_text=script)
    assert r.rc != 2, "a zero still refused with the comparison inverted"


def test_mutation_guarded_pair_tightened_reddens(tmp_path):
    """The other direction: tightening UPLOAD_RETENTION_DAYS to positive must break
    its documented hold, which is what makes the asymmetry leg above meaningful."""
    script = _mutate('require_integer_days UPLOAD_RETENTION_DAYS "${UPLOAD_RETENTION_DAYS}"',
                     'require_positive_days UPLOAD_RETENTION_DAYS "${UPLOAD_RETENTION_DAYS}"')
    r = run_script(tmp_path, env={"UPLOAD_RETENTION_DAYS": "0"}, script_text=script)
    assert r.rc == 2 and NO_OFF in r.err, \
        "tightening the guarded pair did not break their hold -- the asymmetry is not under test"
