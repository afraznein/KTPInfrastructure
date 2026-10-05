import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_reports_unit_timeout_matches_production():
    # Production raised this with a drop-in; a repo unit below it would undo that on install.
    unit = (ROOT / "systemd/ktp-reports.service").read_text(encoding="utf-8")
    values = re.findall(r"^TimeoutStartSec=(\d+)\s*$", unit, re.M)
    assert values == ["5400"]
