from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_full_lane_builds_test_core_from_preprod():
    workflow = (ROOT / ".github/workflows/lane-b-stats-e2e.yml").read_text()
    action = (ROOT / ".github/actions/build-ktpamx-laneb/action.yml").read_text()
    script = (ROOT / "scripts/build_ktpamx_laneb.sh").read_text()

    assert "ref: feat/lane-b-fakeclient-players" not in workflow
    assert "          ref: preprod" in workflow
    assert '-v "${PWD}/.github:/work/.github:ro"' in workflow
    assert "    default: preprod" in action
    assert 'REF="${LANEB_REF:-preprod}"' in script


def test_build_refuses_partial_lane_b_core_support():
    script = (ROOT / "scripts/build_ktpamx_laneb.sh").read_text()

    assert "amxmodx/meta_api.cpp" in script
    assert "modules/dod/dodx/moduleconfig.cpp" in script
    assert "the lane would either run blind or emit no bot weaponstats" in script
