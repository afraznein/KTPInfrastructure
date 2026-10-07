"""ktp-data-server-health.sh: a new ktp_* table without a SELECT grant must page.

A missing per-table grant does not read as "denied" anywhere a consumer looks:
`information_schema` hides what the asking account cannot see, so a capability
probe reports the table ABSENT and the caller concludes the migration never ran.
That exact mistake has been made three times -- a wrong "migration 036 is not
applied" verdict on 2026-09-22, five days of the hitreg monitor's own output
being unreadable, and a blocked move-census verification on 2026-10-05 -- and the
trigger was the same each time: a new table landed and nobody granted it.

The block under test is the policy half, not the query. It decides which
ungranted tables are *unexpected*, which is what lets the check alert instead of
emitting a line into a root-only log nobody reads. Tables ungranted on purpose
(credential stores, dated `_bak_`/`_snap_` copies) must be filtered; anything
else must survive, because surviving is what pages.

Extracted from the shipped script by marker, so renaming or deleting the block
fails this file rather than testing a copy that no longer ships. No database.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % name
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def unexpected(names):
    """Run the shipped reducer over `names`, return the list it would page about."""
    script = block("ktp-grants") + "\ngrants_unexpected\n"
    out = subprocess.run([BASH, "-c", script], input="\n".join(names) + "\n",
                         capture_output=True, text=True, check=True)
    return [l for l in out.stdout.splitlines() if l.strip()]


# The 19 tables actually ungranted on the box, 2026-10-05, measured with the
# LEFT JOIN against information_schema.TABLE_PRIVILEGES (NOT with `comm`, which
# silently mis-sorts -- see knowledge/access-and-self-service.md).
REAL_UNGRANTED = [
    "ktp_ac_detector_review_notes",
    "ktp_ac_download_tokens",
    "ktp_ac_first_login_grants",
    "ktp_ac_identity_review_notes",
    "ktp_ac_player_profiles_bak_20260804",
    "ktp_ac_player_profiles_bak_tzfix_20260807",
    "ktp_ac_players",
    "ktp_ac_profile_actions_bak_20260804",
    "ktp_ac_profile_consent_bak_20260804",
    "ktp_ac_profile_consent_bak_tzfix_20260807",
    "ktp_ac_profile_history_bak_20260728",
    "ktp_ac_profile_history_bak_20260804",
    "ktp_ac_recompute_snapshot_20260727",
    "ktp_ac_session_tokens",
    "ktp_ac_sessions_bak_tzfix_20260807",
    "ktp_ac_snap_077_20260727",
    "ktp_ac_snap_hotfix_20260727",
    "ktp_ac_weapon_fires_dups_bak_20260923",
    "ktp_ac_web_tokens",
]


def test_the_current_box_state_is_silent():
    """Today's 19 are all deliberate, so the check must not page on them.

    If this fails after a ruling grants or locks something, update the list with
    the new measurement -- do not widen the pattern to make it pass.
    """
    assert unexpected(REAL_UNGRANTED) == []


def test_a_new_table_pages():
    """The whole point. A table nobody has ruled on must not be silent."""
    assert unexpected(REAL_UNGRANTED + ["ktp_move_census"]) == ["ktp_move_census"]


def test_credential_stores_stay_filtered():
    for t in ("ktp_ac_download_tokens", "ktp_ac_session_tokens",
              "ktp_ac_web_tokens", "ktp_ac_first_login_grants"):
        assert unexpected([t]) == [], t


def test_the_password_table_stays_filtered():
    """ktp_ac_players carries password_hash / password_hash_v2."""
    assert unexpected(["ktp_ac_players"]) == []


def test_dated_backups_and_snapshots_are_filtered():
    for t in ("ktp_ac_player_profiles_bak_20260804",
              "ktp_ac_profile_consent_bak_tzfix_20260807",
              "ktp_ac_recompute_snapshot_20260727",
              "ktp_ac_snap_hotfix_20260727",
              "ktp_ac_weapon_fires_dups_bak_20260923"):
        assert unexpected([t]) == [], t


def test_a_backup_shaped_name_without_a_date_is_NOT_filtered():
    """The date is what makes it a frozen copy. `ktp_foo_bak` is a live table."""
    assert unexpected(["ktp_foo_bak"]) == ["ktp_foo_bak"]


def test_an_undated_snapshot_name_still_pages():
    assert unexpected(["ktp_ac_snapshot"]) == ["ktp_ac_snapshot"]


def test_empty_input_is_empty_output():
    assert unexpected([]) == []


def test_review_notes_are_filtered_but_remain_unruled():
    """Filtered to avoid paging on an open question, not because it is settled.

    Both carry judgement calls (detector `predicate`s are the published-evasion
    -recipe concern; identity notes are free text about named players). If drew
    rules they should be readable, grant them and drop them from the reducer --
    the filter is a holding position, not the ruling.
    """
    assert unexpected(["ktp_ac_detector_review_notes",
                       "ktp_ac_identity_review_notes"]) == []
