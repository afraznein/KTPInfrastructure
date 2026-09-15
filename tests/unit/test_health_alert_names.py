"""ktp-data-server-health.sh: building the log line must not be able to kill the run.

`names_of` is extracted from the real script between the `# >>> ktp-alert-names`
markers, so renaming or deleting it fails this file rather than silently testing
a copy that no longer ships.

The defect this covers was not visible in the alert itself — it was visible in
what the alert channel STOPPED carrying. Under `set -euo pipefail`,
`printf '%s\\n' "${arr[@]}" | grep -v '^$' | paste -sd, -` exits 1 when the array
is empty, so the run aborted at the assignment: no TRANSITIONS line, no Discord
POST, and no `save_state`, which left the same diff to abort again next hour.
"""
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
BEGIN, END = "# >>> ktp-alert-names", "# <<< ktp-alert-names"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

# The spelling that shipped 2026-08-31. Kept here as the control: every test below
# that asserts the run survives must FAIL against this, or it is asserting nothing.
SHIPPED_2026_08_31 = (
    "names_of() { printf '%s\\n' \"$@\" 2>/dev/null | grep -v '^$' | paste -sd, -; }\n")


def names_source():
    text = SCRIPT.read_text(encoding="utf-8")
    assert BEGIN in text and END in text, "the alert-names markers are gone from the shipped script"
    # Drop the remainder of the marker's own line: it is prose, not shell.
    return text.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]


def run_alert_path(tmp_path, items, source=None, name="probe.sh"):
    """Replay the assignment + the log line it feeds, under the script's own flags.

    Returns (rc, stdout). rc != 0 means the real run would have died before the
    Discord POST.
    """
    body = "set -euo pipefail\n%s\nitems=(%s)\nn=$(names_of ${items[@]+\"${items[@]}\"})\n" \
           "echo \"TRANSITIONS: count=${#items[@]}${n:+ [${n}]}\"\necho REACHED_THE_POST\n" % (
               source if source is not None else names_source(),
               " ".join('"%s"' % i for i in items))
    p = tmp_path / name
    p.write_text(body, encoding="utf-8", newline="\n")
    r = subprocess.run(["bash", p.as_posix()], capture_output=True, text=True)
    return r.returncode, r.stdout


def test_an_empty_side_still_reaches_the_post(tmp_path):
    """A brand-new failure with nothing recovering, which is the ordinary shape
    of a first alert — and the one the shipped spelling threw away."""
    rc, out = run_alert_path(tmp_path, [])
    assert rc == 0
    assert "REACHED_THE_POST" in out
    assert "TRANSITIONS: count=0" in out


def test_the_shipped_spelling_is_what_this_catches(tmp_path):
    """The control. Without it, the test above passes against any implementation."""
    rc, out = run_alert_path(
        tmp_path, [], source=SHIPPED_2026_08_31, name="control.sh")
    assert rc != 0, "the 2026-08-31 spelling is supposed to abort here"
    assert "REACHED_THE_POST" not in out


def test_a_populated_side_is_joined_with_commas(tmp_path):
    rc, out = run_alert_path(tmp_path, ["hltv@27028=deactivating", "disk-growth:/"])
    assert rc == 0
    assert "[hltv@27028=deactivating,disk-growth:/]" in out


def test_one_item_carries_no_separator(tmp_path):
    rc, out = run_alert_path(tmp_path, ["mysql.service=failed"])
    assert rc == 0
    assert "[mysql.service=failed]" in out


def test_empty_elements_are_dropped_not_rendered_as_gaps(tmp_path):
    """What `grep -v '^$'` was there for. Losing it would print `a,,b`."""
    rc, out = run_alert_path(tmp_path, ["a", "", "b"])
    assert rc == 0
    assert "[a,b]" in out


def test_an_item_with_a_space_stays_one_item(tmp_path):
    rc, out = run_alert_path(tmp_path, ["ktp-render-banlist.timer=inactive/enabled",
                                        "hltv-demo-renamer-read=atl bm"])
    assert rc == 0
    assert "[ktp-render-banlist.timer=inactive/enabled,hltv-demo-renamer-read=atl bm]" in out


def test_the_helper_cannot_fail_on_any_input(tmp_path):
    """Whatever it is handed, the run must continue. The whole point is that this
    line is cosmetic and must never decide whether an alert is delivered."""
    for i, items in enumerate([[], [""], ["", ""], ["a"], ["*"], ["$(echo hi)"], ["-n"], ["%s"]]):
        rc, out = run_alert_path(tmp_path, items, name="any%d.sh" % i)
        assert rc == 0, items
        assert "REACHED_THE_POST" in out, items


def test_printf_format_injection_is_not_possible(tmp_path):
    """`-n` and `%s` are real item shapes only by accident, but a helper that
    passed them to printf as a FORMAT would mangle or swallow the line."""
    rc, out = run_alert_path(tmp_path, ["%s%s", "-n"], name="fmt.sh")
    assert rc == 0
    assert "[%s%s,-n]" in out


def test_the_old_spelling_is_gone_from_the_script():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "grep -v '^$' | paste -sd, -" not in text


def test_the_script_still_parses():
    r = subprocess.run(["bash", "-n", SCRIPT.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
