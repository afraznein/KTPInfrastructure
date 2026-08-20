import json
import struct

import pytest

from scripts import analyze_competitive_corpus as corpus
from scripts import build_competitive_report_site as site
from scripts import build_competitive_spatial_configs as configs


def test_overview_geometry_ignores_commented_origins(tmp_path):
    description = tmp_path / "dod_test.txt"
    description.write_text(
        "// ORIGIN 999 888 0\nZOOM 1.25\nORIGIN 10.5 -20.25 0\nROTATED 1\n",
        encoding="utf-8",
    )
    bitmap = tmp_path / "dod_test.bmp"
    header = bytearray(26)
    header[:2] = b"BM"
    struct.pack_into("<ii", header, 18, 1024, 768)
    bitmap.write_bytes(header)

    assert configs.overview_geometry(description, bitmap) == {
        "origin_x": 10.5,
        "origin_y": -20.25,
        "zoom": 1.25,
        "rotated": True,
        "width": 1024,
        "height": 768,
    }


def test_reviewed_flags_preserve_captured_coordinates(tmp_path):
    reviewed = tmp_path / "dod_test.json"
    reviewed.write_text(json.dumps({"flags": [{
        "name": "Friendly", "code": "flag_code", "x": 10, "y": 20,
        "initial_owner": 2,
    }]}), encoding="utf-8")
    flags, evidence = configs.apply_reviewed_flags([
        {"name": "flag_code", "code": "flag_code", "x": 10.0, "y": 20.0,
         "initial_owner": 0},
    ], reviewed)
    assert flags[0]["name"] == "Friendly"
    assert flags[0]["initial_owner"] == 2
    assert evidence["reviewed_flag_overrides"] == 1


def test_public_corpus_export_rejects_player_position_details():
    corpus.assert_public_safe({"players": [{"name": "bot", "kills": 1}]})
    with pytest.raises(ValueError, match="private key leaked"):
        corpus.assert_public_safe({"players": [{"name": "bot", "pos_x": 10}]})
    with pytest.raises(ValueError, match="private key leaked"):
        corpus.assert_public_safe({"players": [{"name": "bot", "steam_id": "BOT:x"}]})


def test_static_explorer_embeds_overview_schema_and_privacy_contract():
    html = site.page_html({
        "dataset_id": "test-dataset",
        "privacy": "aggregate only",
        "integrity": {"maps": 0, "fixtures": 0},
        "maps": [],
        "schema": {"table_count": 0, "fixture_observations": 0, "tables": []},
    })
    assert "Corpus overview" in html
    assert "Schema &amp; coverage" not in html  # source label is rendered by the browser
    assert "Schema & coverage" in html
    assert "aggregate only" in html
