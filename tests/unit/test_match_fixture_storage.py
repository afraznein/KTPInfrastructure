from __future__ import annotations

import gzip
import json

from scripts import match_fixture_storage as storage


SQL = (
    "CREATE TABLE `events` (`id` int, `match_id` varchar(64));\n"
    "INSERT INTO `events` (`id`,`match_id`) VALUES (1,'one-TEST');\n"
    "INSERT INTO `events` (`id`,`match_id`) VALUES (2,'other-TEST');\n"
)


def test_fixture_inspection_separates_framing_and_match_rows(tmp_path):
    fixture = tmp_path / "fixture.sql"
    fixture.write_bytes(SQL.encode())
    result = storage.inspect_fixture(fixture, "one-TEST")
    assert result["container_bytes"] == len(SQL.encode())
    assert result["uncompressed_bytes"] == len(SQL.encode())
    assert 0 < result["canonical_gzip_bytes"] < result["uncompressed_bytes"]
    assert result["insert_rows"] == 2
    assert result["match_tagged_rows"] == 1
    assert result["tables"][0]["table"] == "events"
    assert result["non_insert_bytes"] == len(SQL.splitlines(keepends=True)[0].encode())


def test_gzip_reports_compressed_and_uncompressed_identity(tmp_path):
    fixture = tmp_path / "fixture.sql.gz"
    with gzip.open(fixture, "wb") as handle:
        handle.write(SQL.encode())
    result = storage.inspect_fixture(fixture, "one-TEST")
    assert result["container_bytes"] == fixture.stat().st_size
    assert result["uncompressed_bytes"] == len(SQL.encode())
    assert result["container_sha256"] != result["uncompressed_sha256"]


def test_report_never_claims_a_human_baseline(tmp_path):
    fixture = tmp_path / "fixture.sql"
    fixture.write_text(SQL, encoding="utf-8")
    inspected = storage.inspect_fixture(fixture, "one-TEST")
    report = storage.build_report(inspected, [inspected], "synthetic bot corpus")
    assert report["human_baseline"]["available"] is False
    assert report["projection"]["matches"]["100"] == inspected["canonical_gzip_bytes"] * 100
    rendered = storage.render_markdown(report)
    assert "not live InnoDB" in rendered
    assert "Unavailable until reviewed human fixtures exist" in rendered


def test_cli_writes_json_and_markdown(tmp_path):
    fixture = tmp_path / "fixture.sql"
    fixture.write_text(SQL, encoding="utf-8")
    output = tmp_path / "out"
    assert storage.main([
        str(fixture), "--match-id", "one-TEST", "--comparison", str(fixture),
        "--output-dir", str(output),
    ]) == 0
    payload = json.loads((output / "match-fixture-storage.json").read_text())
    assert payload["measurement"] == "portable_sql_fixture_not_live_database_allocation"
    assert (output / "MATCH_FIXTURE_STORAGE.md").is_file()
