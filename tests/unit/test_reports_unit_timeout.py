import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_reports_unit_timeout_matches_the_per_query_bound():
    # 600 is the subprocess timeout every query in the job already carries, so
    # the job cannot outlive its own slowest permitted step. The old 5400 was a
    # drop-in value copied into the repo; it outran the timer period and made
    # one slow period cost two 90-minute wedges instead of one failed run.
    unit = (ROOT / "systemd/ktp-reports.service").read_text(encoding="utf-8")
    values = re.findall(r"^TimeoutStartSec=(\d+)\s*$", unit, re.M)
    assert values == ["600"]


def test_the_job_steps_are_bounded_at_that_same_value():
    # If this moves, the unit bound above is no longer derived from anything.
    for rel in ("scripts/report_service.py", "scripts/report_sync.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "timeout=600" in src, rel
