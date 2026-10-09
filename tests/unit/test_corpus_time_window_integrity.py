"""The position/producer-clock corpus integrity queries, executed against a fixture.

The defect these two files pin is a SILENT UNDERCOUNT, not an error: a row whose
`event_time` is `FROM_UNIXTIME(0)` is invisible to every time-windowed query and
visible to every bare `COUNT(*)`, so two honest queries over one corpus disagree
and neither reports a gap. A query that detects it is only worth having if the
detection itself is tested, and the detection has one specific way of failing
silently -- the predicate that *looks* right,

    WHERE event_time = '1970-01-01 00:00:00'

returns a clean zero over a populated table, because the stored value is
`FROM_UNIXTIME(0)` rendered in the MySQL SESSION zone and this host is
`America/New_York`, where it renders `1969-12-31 19:00:00`.

So this module does three things, and the third is the one that matters:

  1. asserts the two shipped files keep the properties their definitions depend
     on -- a FLOOR rather than an equality, no percentage, and a defect-B
     denominator that excludes the by-design NULL population,
  2. runs the shipped sections C, D, E, F, G and H -- the statement text, read
     out of the file, not a re-implementation -- against a sqlite fixture seeded
     to STRADDLE every boundary they test,
  3. mutates both the predicate and the fixture and shows each assertion going
     red, because an assertion that cannot fail and a control that never ran are
     the same bug in different clothes.

NON-VACUITY IS ASSERTED FROM THE FIXTURE ITSELF. A fixture whose rows all fall
on one side of the floor cannot fail the way this bug fails, and it would pass
every assertion below while testing nothing. `test_fixture_straddles_*` are
therefore not scaffolding -- they are the controls, and an emptied or one-sided
fixture fails them by name.

WHAT THIS DOES NOT PROVE
  - that MySQL parses these statements. Nothing here runs MySQL. The translator
    below is narrow and refuses what it does not recognise, which converts a
    statement rewritten into an unsupported shape into a failure rather than
    into a plausible zero -- but that is a guard against drift, not a parser.
  - anything about the live corpus. Production reads are not available from
    here. The counts in this module are the fixture's, and the real measurement
    is the command in the files' own headers.
  - that `event_time` is UTC. It is not: it is a UTC epoch rendered in the DB
    session zone, and several checked-in readers already window on it against
    other columns from that same clock. Nothing here re-stamps anything.
"""
import pathlib
import re
import sqlite3

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
POSITION_SQL = REPO / "sql" / "integrity" / "position_corpus_integrity.sql"
PRODUCER_SQL = REPO / "sql" / "integrity" / "producer_clock_corpus_integrity.sql"

# The five streams whose INSERT derives a DATETIME from the epoch-zero default.
STREAMS = (
    "ktp_position_samples",
    "ktp_shot_events",
    "ktp_move_census",
    "ktp_aim_vis",
    "ktp_flag_state_events",
)

# Three renderings of FROM_UNIXTIME(0) that have to be caught by one predicate:
# the America/New_York one this host produces, the UTC one a doc would guess,
# and a third zone, so the test cannot pass by hardcoding either of the first
# two. All three are below the floor and none is reachable by real data.
EPOCH_ZERO_LITERALS = ("1969-12-31 19:00:00", "1970-01-01 00:00:00", "1970-01-01 05:00:00")
GUESSED_EQUALITY = "1970-01-01 00:00:00"


# ---------------------------------------------------------------------------
# reading the shipped files
# ---------------------------------------------------------------------------

def _text(path):
    assert path.is_file(), "%s is not on this tree" % path
    body = path.read_text(encoding="utf-8")
    assert len(body) > 4000, "%s is implausibly short -- read the wrong file?" % path.name
    return body


def _comment_spans(sql):
    """Yield (line_number, text) for each `--` comment, string literals excluded.

    A naive `line.find("--")` is wrong in the expensive direction here: section
    E's reading strings are prose, and a `--` inside one would cut the statement
    at a quote and leave an unterminated literal. That is the same class of
    defect these files exist to catch, so the scanner has to know about quotes.
    """
    line_no, i, n = 1, 0, len(sql)
    in_str = False
    while i < n:
        ch = sql[i]
        if ch == "\n":
            line_no += 1
            i += 1
            continue
        if in_str:
            if ch == "'":
                in_str = sql[i + 1:i + 2] == "'"
                i += 2 if in_str else 1
                continue
            i += 1
            continue
        if ch == "'":
            in_str = True
            i += 1
            continue
        if ch == "-" and sql[i + 1:i + 2] == "-":
            end = sql.find("\n", i)
            end = n if end < 0 else end
            yield line_no, sql[i:end]
            i = end
            continue
        i += 1


def _uncommented(sql):
    """Strip `--` comments, leaving string literals intact."""
    out, cursor = [], 0
    for _, text in _comment_spans(sql):
        at = sql.find(text, cursor)
        out.append(sql[cursor:at])
        cursor = at + len(text)
    out.append(sql[cursor:])
    return "".join(out)


def _statements(sql):
    stmts = [s.strip() for s in _uncommented(sql).split(";")]
    return [s for s in stmts if s]


def _sections(sql):
    """Map `SECTION <letter(s)>` banner -> the statements under it."""
    banner = re.compile(r"^--\s*SECTION\s+([A-Z][0-9]?)\b", re.M)
    hits = list(banner.finditer(sql))
    assert hits, "no SECTION banners found -- the file layout changed"
    out = {}
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(sql)
        out[m.group(1)] = _statements(sql[m.start():end])
    return out


# ---------------------------------------------------------------------------
# the narrow MySQL -> sqlite translator
#
# It handles exactly the constructs these two files use in the sections that
# touch data, and refuses anything else. Sections A and B are environment and
# preflight -- `@@session.time_zone`, `information_schema`, `PREPARE` -- and are
# deliberately out of scope: they report the host, they compute no defect count.
#
# The one translation that could change an ANSWER rather than only syntax is
# collation. Migration 013 put these tables on utf8mb4_unicode_ci, so `match_id`
# compares case-INsensitively unless BINARY is forced. The fixture therefore
# declares `match_id TEXT COLLATE NOCASE`, which makes `=` case-insensitive like
# MySQL, and `BINARY a = BINARY b` is rewritten to `a = b COLLATE BINARY`, which
# is the bytewise answer. Both readings exist in the checked-in consumers, which
# is why the files report them separately and why the test exercises both.
# ---------------------------------------------------------------------------

_REFUSED = (
    "@@",
    "information_schema",
    "PREPARE ",
    "EXECUTE ",
    "DEALLOCATE ",
    "max_execution_time",
)


class Refused(Exception):
    pass


def _translate(stmt, floor):
    if any(tok.lower() in stmt.lower() for tok in _REFUSED):
        raise Refused(stmt[:120])
    out = stmt
    out = out.replace("@epoch_floor", "'%s'" % floor)
    out = re.sub(r"@since_\w+", "0", out)
    out = re.sub(r"\bIF\s*\(", "IIF(", out)
    out = re.sub(r"\bAS\s+CHAR\b", "AS TEXT", out, flags=re.I)
    # BINARY x = BINARY y  ->  x = y COLLATE BINARY
    out = re.sub(r"\bBINARY\s+([\w.]+)\s*=\s*BINARY\s+([\w.]+)",
                 r"\1 = \2 COLLATE BINARY", out)
    if re.search(r"\bBINARY\b(?!\s*\))", out) and "COLLATE BINARY" not in out:
        raise Refused("an untranslated BINARY survived: %s" % out[:120])
    return out


def _connect():
    conn = sqlite3.connect(":memory:")
    conn.create_function("CONCAT", -1, lambda *a: "".join("" if x is None else str(x) for x in a))
    conn.create_function("CONCAT_WS", -1,
                         lambda sep, *a: str(sep).join("" if x is None else str(x) for x in a))
    conn.create_function("FIELD", -1,
                         lambda v, *a: (list(a).index(v) + 1) if v in a else 0)
    conn.create_function("NOW", 0, lambda: "2026-10-09 12:00:00")
    conn.create_function("DATABASE", 0, lambda: "hlstatsx")
    conn.create_function("UNIX_TIMESTAMP", 1, lambda s: 0 if s is None else 1)
    return conn


# ---------------------------------------------------------------------------
# the fixture -- seeded to straddle every boundary the queries test
# ---------------------------------------------------------------------------

_SHARED_DDL = """
CREATE TABLE ktp_matches (
    id INTEGER PRIMARY KEY, match_id TEXT COLLATE NOCASE NOT NULL,
    half INTEGER NOT NULL, start_time TEXT, end_time TEXT, created_at TEXT);
CREATE TABLE ktp_flag_positions (
    id INTEGER PRIMARY KEY, last_match_id TEXT COLLATE NOCASE,
    last_event_epoch INTEGER, updated_at TEXT);
"""

_STREAM_DDL = """
CREATE TABLE {t} (
    id INTEGER PRIMARY KEY, match_id TEXT COLLATE NOCASE, half INTEGER NOT NULL,
    event_time TEXT NOT NULL, event_epoch INTEGER, created_at TEXT NOT NULL);
"""

GOOD_TIME = "2026-09-20 21:14:03"
GOOD_EPOCH = 1789000000
INGESTED = "2026-08-25 03:11:00"


def _seed_shared(conn):
    conn.executescript(_SHARED_DDL)
    conn.executemany(
        "INSERT INTO ktp_matches (match_id, half, start_time, end_time, created_at)"
        " VALUES (?,?,?,?,?)",
        [("m1", 1, GOOD_TIME, GOOD_TIME, INGESTED),
         ("m1", 2, GOOD_TIME, GOOD_TIME, INGESTED),
         ("m2", 1, GOOD_TIME, GOOD_TIME, INGESTED),
         # Upper-case on purpose: 'm3' below matches it case-insensitively and
         # not bytewise, which is the case_variant_match_ids population.
         ("M3", 1, GOOD_TIME, GOOD_TIME, INGESTED)])
    conn.executemany(
        "INSERT INTO ktp_flag_positions (last_match_id, last_event_epoch, updated_at)"
        " VALUES (?,?,?)",
        [("m1", GOOD_EPOCH, INGESTED), ("m1", 0, INGESTED), ("mX", GOOD_EPOCH, INGESTED),
         ("m1", None, INGESTED)])
    conn.commit()


def _seed_stream(conn, table, extra=0):
    """Seed one stream table.

    `extra` adds that many further clean rows, so every stream in the
    five-table run has a DIFFERENT total. A section that silently read the
    wrong table then returns the wrong number instead of a plausible one.
    """
    conn.executescript(_STREAM_DDL.format(t=table))
    rows = []
    # DEFECT A, three renderings, on a match half that DOES exist -- so the
    # epoch-zero population is not confounded with the orphan population.
    for lit in EPOCH_ZERO_LITERALS:
        for _ in range(2):
            rows.append(("m1", 1, lit, 0, INGESTED))
    # Clean rows, above the floor. Ten of them, so the gap is a minority and a
    # test that accidentally counted everything would not look right.
    for _ in range(10):
        rows.append(("m1", 1, GOOD_TIME, GOOD_EPOCH, INGESTED))
    # DEFECT B1 -- no ktp_matches row for this id at all.
    rows.append(("mX", 1, GOOD_TIME, GOOD_EPOCH, INGESTED))
    rows.append(("mX", 1, GOOD_TIME, GOOD_EPOCH, INGESTED))
    # DEFECT B2 -- the match exists, half 2 of it never recorded.
    rows.append(("m2", 2, GOOD_TIME, GOOD_EPOCH, INGESTED))
    # NOT a defect -- the daemon writes NULL deliberately when it held no live
    # match context. Counting these is the withdrawn 2026-10-05 definition.
    for _ in range(5):
        rows.append((None, 0, GOOD_TIME, GOOD_EPOCH, INGESTED))
    # B3 -- an empty string is a different defect, on the producer side.
    rows.append(("", 0, GOOD_TIME, GOOD_EPOCH, INGESTED))
    # Case variant -- resolves to M3 case-insensitively, not bytewise.
    rows.append(("m3", 1, GOOD_TIME, GOOD_EPOCH, INGESTED))
    for _ in range(extra):
        rows.append(("m1", 1, GOOD_TIME, GOOD_EPOCH, INGESTED))

    conn.executemany(
        "INSERT INTO %s (match_id, half, event_time, event_epoch, created_at)"
        " VALUES (?,?,?,?,?)" % table, rows)
    conn.commit()
    return len(rows)


BASE_TOTAL = 26
EXPECTED_EPOCH_ZERO = 6
EXPECTED_NULL_MATCH = 5
EXPECTED_B1_ROWS = 2
EXPECTED_B2_ROWS = 1
EXPECTED_EMPTY_STRING = 1
# The whole reason this bug is expensive: the slice is a minority, so a wrong
# figure looks plausible. Keep it that way in the fixture too.
assert EXPECTED_EPOCH_ZERO * 3 < BASE_TOTAL


@pytest.fixture()
def db():
    conn = _connect()
    _seed_shared(conn)
    seeded = _seed_stream(conn, "ktp_position_samples")
    assert seeded == BASE_TOTAL, "fixture size drifted from the expectations below"
    yield conn
    conn.close()


def _floor(sql):
    m = re.search(r"@epoch_floor\s*:=\s*'([^']+)'", sql)
    assert m, "no @epoch_floor literal found -- the definition moved"
    return m.group(1)


def _rows(conn, stmt):
    cur = conn.execute(stmt)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ===========================================================================
# the controls: the fixture has to straddle, or nothing below measures anything
# ===========================================================================

def test_fixture_straddles_the_epoch_floor(db):
    floor = _floor(_text(POSITION_SQL))
    below = db.execute("SELECT COUNT(*) FROM ktp_position_samples WHERE event_time < ?",
                       (floor,)).fetchone()[0]
    above = db.execute("SELECT COUNT(*) FROM ktp_position_samples WHERE event_time >= ?",
                       (floor,)).fetchone()[0]
    assert below == EXPECTED_EPOCH_ZERO, "no row below the floor -- the fixture is one-sided"
    assert above > 0, "no row above the floor -- the fixture is one-sided"
    assert below + above == BASE_TOTAL


def test_fixture_straddles_every_defect_b_population(db):
    q = "SELECT COUNT(*) FROM ktp_position_samples WHERE %s"
    null_rows = db.execute(q % "match_id IS NULL").fetchone()[0]
    empty_rows = db.execute(q % "match_id = ''").fetchone()[0]
    b1 = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples p WHERE p.match_id IS NOT NULL"
        " AND p.match_id <> '' AND NOT EXISTS"
        " (SELECT 1 FROM ktp_matches m WHERE m.match_id = p.match_id)").fetchone()[0]
    b2 = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples p WHERE p.match_id IS NOT NULL"
        " AND p.match_id <> ''"
        " AND EXISTS (SELECT 1 FROM ktp_matches m WHERE m.match_id = p.match_id)"
        " AND NOT EXISTS (SELECT 1 FROM ktp_matches m"
        "                 WHERE m.match_id = p.match_id AND m.half = p.half)").fetchone()[0]
    clean = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples p WHERE EXISTS"
        " (SELECT 1 FROM ktp_matches m WHERE m.match_id = p.match_id"
        "  AND m.half = p.half)").fetchone()[0]
    assert null_rows == EXPECTED_NULL_MATCH, "no by-design NULL rows -- the denominator is untested"
    assert empty_rows == EXPECTED_EMPTY_STRING, "no empty-string rows -- B3 is untested"
    assert b1 == EXPECTED_B1_ROWS, "no B1 orphans -- the per-match gap is untested"
    assert b2 == EXPECTED_B2_ROWS, "no B2 orphans -- the per-half gap is untested"
    assert clean > 0, "every row is a defect -- a predicate that matched everything would pass"


def test_fixture_carries_more_than_one_rendering_of_epoch_zero(db):
    distinct = db.execute(
        "SELECT COUNT(DISTINCT event_time) FROM ktp_position_samples WHERE event_epoch = 0"
    ).fetchone()[0]
    assert distinct == len(EPOCH_ZERO_LITERALS) >= 3, (
        "one rendering only -- an equality predicate would score as well as the floor")


# ===========================================================================
# the silent undercount, reproduced
# ===========================================================================

def test_a_time_window_silently_drops_the_epoch_zero_slice(db):
    """The shape of the bug: two honest queries, no error, different answers."""
    bare = db.execute("SELECT COUNT(*) FROM ktp_position_samples").fetchone()[0]
    windowed = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples"
        " WHERE event_time >= '2026-01-01 00:00:00' AND event_time <= NOW()").fetchone()[0]
    assert bare == BASE_TOTAL
    assert windowed == BASE_TOTAL - EXPECTED_EPOCH_ZERO
    assert bare - windowed == EXPECTED_EPOCH_ZERO
    assert windowed > 0, "the window matched nothing -- this would pass for the wrong reason"


def test_the_guessed_equality_undercounts_and_can_read_a_clean_zero(db):
    """Why the pinned definition is a FLOOR.

    The equality against the 1970 literal finds only the rows that happen to be
    stored in that rendering, and if the host zone shifts it finds none at all --
    over a table with six defective rows in it, and with nothing reporting a gap.
    """
    floor = _floor(_text(POSITION_SQL))
    by_floor = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples WHERE event_time < ?", (floor,)).fetchone()[0]
    by_equality = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples WHERE event_time = ?",
        (GUESSED_EQUALITY,)).fetchone()[0]
    assert by_floor == EXPECTED_EPOCH_ZERO
    assert 0 < by_equality < by_floor, "the equality did not undercount -- fixture lost a rendering"

    # And the full clean zero, which is the shape that produced the original
    # wrong reading: no row is stored in THIS rendering at all.
    db.execute("DELETE FROM ktp_position_samples WHERE event_time = ?", (GUESSED_EQUALITY,))
    still_defective = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples WHERE event_time < ?", (floor,)).fetchone()[0]
    clean_zero = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples WHERE event_time = ?",
        (GUESSED_EQUALITY,)).fetchone()[0]
    assert still_defective > 0
    assert clean_zero == 0


def test_the_withdrawn_null_or_zero_definition_scores_by_design_rows_as_defects(db):
    """Why defect B's denominator excludes NULL, stated as a measurement."""
    pinned = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples p WHERE p.match_id IS NOT NULL"
        " AND p.match_id <> '' AND NOT EXISTS"
        " (SELECT 1 FROM ktp_matches m WHERE m.match_id = p.match_id)").fetchone()[0]
    withdrawn = db.execute(
        "SELECT COUNT(*) FROM ktp_position_samples p WHERE p.match_id IS NULL"
        " OR p.half = 0 OR NOT EXISTS"
        " (SELECT 1 FROM ktp_matches m WHERE m.match_id = p.match_id)").fetchone()[0]
    assert pinned == EXPECTED_B1_ROWS
    assert withdrawn >= pinned + EXPECTED_NULL_MATCH, (
        "the two definitions agreed -- then the fixture has no by-design population")


# ===========================================================================
# the shipped statements, executed
# ===========================================================================

def _position_section(letter):
    sql = _text(POSITION_SQL)
    return _sections(sql)[letter], _floor(sql)


def test_shipped_position_section_c_reports_the_gap(db):
    stmts, floor = _position_section("C")
    assert len(stmts) == 1, "section C is no longer one statement"
    rows = _rows(db, _translate(stmts[0], floor))
    got = {r["metric"]: r["value"] for r in rows}
    assert got["C rows_a_bare_COUNT_sees"] == str(BASE_TOTAL)
    assert got["C rows_any_time_filter_sees"] == str(BASE_TOTAL - EXPECTED_EPOCH_ZERO)
    assert got["C GAP_time_filter_silently_loses"] == str(EXPECTED_EPOCH_ZERO)
    assert got["A epoch_zero_rows"] == str(EXPECTED_EPOCH_ZERO)
    assert got["A epoch_zero_first_inserted_at"] == INGESTED, (
        "created_at did not survive on a defective row -- the repair clock is gone")
    assert got["usable_event_time_earliest"] == GOOD_TIME


def test_shipped_position_section_d_reports_both_orphan_grains(db):
    stmts, floor = _position_section("D")
    assert len(stmts) == 1, "section D is no longer one statement"
    rows = _rows(db, _translate(stmts[0], floor))
    got = {r["metric"]: r["value"] for r in rows}
    with_id = BASE_TOTAL - EXPECTED_NULL_MATCH - EXPECTED_EMPTY_STRING
    assert got["D rows_with_a_match_id"] == str(with_id)
    assert got["D GAP_per_match_join_loses"] == str(EXPECTED_B1_ROWS)
    assert got["D GAP_per_half_join_loses"] == str(EXPECTED_B1_ROWS + EXPECTED_B2_ROWS)
    assert got["B1 orphan_match_rows"] == str(EXPECTED_B1_ROWS)
    assert got["B1 orphan_match_ids"] == "1"
    assert got["B2 orphan_half_rows"] == str(EXPECTED_B2_ROWS)
    assert got["B case_variant_match_ids"] == "1", (
        "the BINARY and non-BINARY readings agreed -- the case-variant row is gone")
    assert got["not_a_defect rows_match_id_null"] == str(EXPECTED_NULL_MATCH)
    assert got["B3 rows_match_id_empty_string"] == str(EXPECTED_EMPTY_STRING)
    # The file's own reconciliation rule, run rather than read.
    assert (int(got["D rows_with_a_match_id"])
            + int(got["not_a_defect rows_match_id_null"])
            + int(got["B3 rows_match_id_empty_string"])) == BASE_TOTAL


def test_shipped_position_controls_read_as_the_file_says_they_must(db):
    stmts, floor = _position_section("E")
    rows = _rows(db, _translate(stmts[0], floor))
    got = {r["control"]: r["value"] for r in rows}
    assert int(got["ctl_position_rows_must_be_nonzero"]) > 0
    assert int(got["ctl_match_rows_must_be_nonzero"]) > 0
    assert int(got["ctl_rows_in_a_sane_window_must_be_nonzero"]) > 0
    assert got["ctl_impossible_future_must_be_zero"] == "0"
    assert got["ctl_nonsense_match_id_must_be_zero"] == "0"


def test_shipped_position_section_f_prints_every_rendering(db):
    stmts, floor = _position_section("F")
    rows = _rows(db, _translate(stmts[0], floor))
    assert {r["stored_literal"] for r in rows} == set(EPOCH_ZERO_LITERALS), (
        "section F did not surface every stored rendering -- a reader would learn the wrong one")
    assert sum(r["rows_with_it"] for r in rows) == EXPECTED_EPOCH_ZERO


def test_shipped_position_section_h_cross_check_agrees_with_the_floor(db):
    stmts, floor = _position_section("H")
    rows = _rows(db, _translate(stmts[0], floor))
    assert len(rows) == 1
    r = rows[0]
    assert r["both_markers_agree"] == EXPECTED_EPOCH_ZERO
    assert r["near_epoch_time_but_epoch_not_zero"] == 0
    assert r["epoch_zero_marker_but_time_looks_fine"] == 0


@pytest.fixture()
def five_streams():
    """All five stream tables in one database, each with a DIFFERENT total.

    The producer file's sections C, D1, D2, F and H are single statements over a
    five-way UNION, so they need every table present. Giving each stream its own
    row count is what makes a mis-referenced table a failure: a branch pointed at
    the wrong table returns another stream's number, not a plausible one.
    """
    conn = _connect()
    _seed_shared(conn)
    totals = {}
    for extra, stream in enumerate(STREAMS):
        totals[stream] = _seed_stream(conn, stream, extra=extra)
    assert len(set(totals.values())) == len(STREAMS), (
        "two streams got the same total -- a mis-referenced table would pass")
    yield conn, totals
    conn.close()


def test_shipped_producer_sections_run_on_every_stream(five_streams):
    """The four streams the position file names and does not measure, plus it."""
    conn, totals = five_streams
    sql = _text(PRODUCER_SQL)
    sections = _sections(sql)
    floor = _floor(sql)
    for letter in ("C", "D1", "D2", "E", "F", "G", "H"):
        assert letter in sections, "section %s vanished from %s" % (letter, PRODUCER_SQL.name)

    c_rows = _rows(conn, _translate(_only(sections["C"]), floor))
    d1_rows = _rows(conn, _translate(_only(sections["D1"]), floor))
    d2_rows = _rows(conn, _translate(_only(sections["D2"]), floor))
    h_rows = _rows(conn, _translate(_only(sections["H"]), floor))
    f_rows = _rows(conn, _translate(_only(sections["F"]), floor))

    for stream in STREAMS:
        total = totals[stream]
        row = _one(c_rows, "stream", stream)
        assert row["rows_a_bare_count_sees"] == total, stream
        assert row["gap_time_filter_loses"] == EXPECTED_EPOCH_ZERO, stream
        assert row["rows_a_time_filter_sees"] == total - EXPECTED_EPOCH_ZERO, stream
        assert row["epoch_zero_last_inserted_at"] == INGESTED, stream

        row = _one(d1_rows, "stream", stream)
        assert row["gap_per_match_join_loses"] == EXPECTED_B1_ROWS, stream
        assert row["gap_per_half_join_loses"] == EXPECTED_B1_ROWS + EXPECTED_B2_ROWS, stream
        assert row["b2_orphan_half_rows"] == EXPECTED_B2_ROWS, stream
        assert row["case_variant_match_ids"] == 1, stream

        row = _one(d2_rows, "stream", stream)
        assert row["not_a_defect_rows_match_id_null"] == EXPECTED_NULL_MATCH, stream
        assert row["b3_rows_match_id_empty_string"] == EXPECTED_EMPTY_STRING, stream
        # The file's own cross-section reconciliation, run rather than read.
        assert row["reconcile_total_must_equal_section_c"] == total, stream

        row = _one(h_rows, "stream", stream)
        assert row["both_markers_agree"] == EXPECTED_EPOCH_ZERO, stream

        mine = [r for r in f_rows if r["stream"] == stream]
        assert {r["stored_literal"] for r in mine} == set(EPOCH_ZERO_LITERALS), stream


def test_shipped_producer_section_g_reads_the_sixth_site(five_streams):
    """ktp_flag_positions stores no derived DATETIME, so it has its own section."""
    conn, _ = five_streams
    sql = _text(PRODUCER_SQL)
    rows = _rows(conn, _translate(_only(_sections(sql)["G"]), _floor(sql)))
    assert len(rows) == 1
    r = rows[0]
    assert r["flag_position_rows"] == 4
    assert r["last_event_epoch_zero"] == 1, "the zero-epoch upsert row is gone"
    assert r["last_event_epoch_null_pre_021"] == 1
    assert r["last_match_id_orphan"] == 1


def test_shipped_producer_controls_read_as_the_file_says_they_must(five_streams):
    conn, totals = five_streams
    sql = _text(PRODUCER_SQL)
    rows = _rows(conn, _translate(_only(_sections(sql)["E"]), _floor(sql)))
    got = {(r["control"], r["stream"]): r["value"] for r in rows}
    for stream in STREAMS:
        assert int(got[("ctl_rows_must_be_nonzero", stream)]) == totals[stream], stream
    assert int(got[("ctl_match_rows_must_be_nonzero", "ktp_matches")]) > 0
    assert int(got[("ctl_sane_window_must_be_nonzero", "ktp_flag_state_events")]) > 0
    assert got[("ctl_impossible_future_must_be_zero", "ktp_flag_state_events")] == "0"
    assert got[("ctl_nonsense_match_id_must_be_zero", "ktp_flag_state_events")] == "0"
    # The two structural controls: these columns are NOT NULL in the live DDL,
    # so the fixture's by-design NULL rows must NOT be reachable there. The
    # fixture deliberately allows them, which is why this reads non-zero and is
    # asserted as such -- a 0 here would mean the control cannot discriminate.
    assert int(got[("ctl_aim_vis_match_id_nulls_must_be_zero", "ktp_aim_vis")]) \
        == EXPECTED_NULL_MATCH


def _only(stmts):
    assert len(stmts) == 1, "expected exactly one statement, got %d" % len(stmts)
    return stmts[0]


def _one(rows, key, value):
    hits = [r for r in rows if r[key] == value]
    assert len(hits) == 1, "expected one %s=%s row, got %d" % (key, value, len(hits))
    return hits[0]


# ===========================================================================
# properties of the shipped text
# ===========================================================================

@pytest.mark.parametrize("path", [POSITION_SQL, PRODUCER_SQL])
def test_the_epoch_test_is_a_floor_and_never_an_equality(path):
    body = _uncommented(_text(path))
    assert re.search(r"event_time\s*<\s*@epoch_floor", body), (
        "the floor predicate is gone -- an equality reads a clean zero on this host")
    assert not re.search(r"event_time\s*=\s*'19[67]\d-", body), (
        "an equality against a 1970-era literal is back in the executable text")
    floor = _floor(_text(path))
    assert floor.startswith("1971-"), "the floor moved off 1971 -- restate why before changing it"


@pytest.mark.parametrize("path", [POSITION_SQL, PRODUCER_SQL])
def test_no_comment_carries_a_semicolon(path):
    """Both files claim this. A splitter that cuts on `;` depends on it."""
    spans = list(_comment_spans(_text(path)))
    assert len(spans) > 50, "almost no comments found -- the scanner is broken, not the file"
    offenders = [n for n, text in spans if ";" in text]
    assert not offenders, "comment semicolons at lines %s would sever a statement" % offenders


@pytest.mark.parametrize("path", [POSITION_SQL, PRODUCER_SQL])
def test_no_percentage_is_reported(path):
    body = _uncommented(_text(path))
    assert "* 100" not in body and "*100" not in body, (
        "a percentage is back -- it falls over a growing corpus while nothing is fixed")


@pytest.mark.parametrize("path", [POSITION_SQL, PRODUCER_SQL])
def test_defect_b_denominator_excludes_the_by_design_null_population(path):
    body = _uncommented(_text(path))
    assert re.search(r"match_id IS NOT NULL AND\s+\S*match_id <> ''", body) or \
           re.search(r"match_id IS NOT NULL AND match_id <> ''", body), (
        "the non-empty guard on defect B's denominator is gone -- the withdrawn "
        "null-or-zero definition scores by-design rows as defects")
    assert "rows_match_id_null" in body, (
        "the by-design population is no longer printed, so somebody will re-derive it")


def test_producer_preflight_manifest_lists_every_stream_and_column():
    """Section B is not executed here, so assert it by its text instead.

    It is the only part of the file that fails CLOSED -- a column named wrongly
    there halts the run with a sentinel rather than reporting a wrong number --
    but a column LEFT OUT fails open: the shape goes unchecked and the sections
    below run against a table that may not have it.
    """
    sql = _text(PRODUCER_SQL)
    preflight = " ".join(_sections(sql)["B"])
    pairs = set(re.findall(r"'(ktp_\w+)',\s*'(\w+)'", preflight)) | set(
        re.findall(r"SELECT '(ktp_\w+)'\s+AS tbl,\s*'(\w+)'\s+AS col", preflight))
    wanted = {(s, c) for s in STREAMS
              for c in ("id", "match_id", "half", "event_time", "event_epoch", "created_at")}
    assert pairs == wanted, "preflight manifest drift: missing %s / extra %s" % (
        sorted(wanted - pairs), sorted(pairs - wanted))


def test_producer_file_covers_every_stream_the_position_file_names():
    body = _text(PRODUCER_SQL)
    for stream in STREAMS:
        assert body.count(stream) >= 3, "%s is barely referenced" % stream
    # Two controls that must NOT appear: a table outside the five, and a
    # nonsense name. Either hitting would mean the count above proves nothing.
    assert body.count("ktp_duel_stats") == 0
    assert body.count("ktp_no_such_stream_zzz") == 0


def test_both_files_refuse_to_be_run_against_the_wrong_engine():
    for path in (POSITION_SQL, PRODUCER_SQL):
        first = _text(path).splitlines()[0]
        assert first.startswith("-- ENGINE: mysql"), (
            "%s lost its engine declaration -- the operator queue cannot tell "
            "the two engines apart without it" % path.name)


# ===========================================================================
# mutation tests -- each assertion above has to be able to fail
# ===========================================================================

def test_mutation_turning_the_floor_into_an_equality_breaks_the_gap(db):
    stmts, floor = _position_section("C")
    mutated = stmts[0].replace("event_time <  @epoch_floor", "event_time =  @epoch_floor")
    assert mutated != stmts[0], "the mutation did not apply -- this test is vacuous"
    rows = _rows(db, _translate(mutated, floor))
    got = {r["metric"]: r["value"] for r in rows}
    assert got["C GAP_time_filter_silently_loses"] == "0", (
        "an equality against the floor should find nothing -- if it does not, the "
        "fixture stores a row AT the floor and this mutation proves nothing")
    assert got["A epoch_zero_rows"] == "0"


def test_mutation_dropping_the_non_empty_guard_inflates_defect_b(db):
    stmts, floor = _position_section("D")
    mutated = stmts[0].replace("q.match_id IS NOT NULL AND q.match_id <> ''",
                               "1 = 1")
    assert mutated != stmts[0], "the mutation did not apply -- this test is vacuous"
    rows = _rows(db, _translate(mutated, floor))
    got = {r["metric"]: r["value"] for r in rows}
    assert int(got["B1 orphan_match_rows"]) > EXPECTED_B1_ROWS, (
        "removing the denominator guard did not change the answer")
    assert int(got["B1 orphan_match_rows"]) >= EXPECTED_B1_ROWS + EXPECTED_NULL_MATCH


def test_mutation_a_one_sided_fixture_fails_the_straddle_control(db):
    floor = _floor(_text(POSITION_SQL))
    db.execute("DELETE FROM ktp_position_samples WHERE event_time < ?", (floor,))
    with pytest.raises(AssertionError, match="one-sided"):
        test_fixture_straddles_the_epoch_floor(db)


def test_mutation_an_emptied_fixture_fails_the_defect_b_control(db):
    db.execute("DELETE FROM ktp_position_samples")
    with pytest.raises(AssertionError):
        test_fixture_straddles_every_defect_b_population(db)


def test_mutation_the_floor_property_check_reddens_on_a_mutated_body(tmp_path):
    mutated = tmp_path / "mutated.sql"
    body = _text(POSITION_SQL).replace("event_time <  @epoch_floor",
                                       "event_time =  '1970-01-01 00:00:00'")
    assert body != _text(POSITION_SQL), "the mutation did not apply -- this test is vacuous"
    mutated.write_text(body, encoding="utf-8", newline="\n")
    with pytest.raises(AssertionError):
        test_the_epoch_test_is_a_floor_and_never_an_equality(mutated)


def test_the_comment_scanner_ignores_a_double_dash_inside_a_string_literal():
    """The scanner's own correctness, because the file checks depend on it.

    Section E's reading strings are prose. A `--` inside one, treated as a
    comment, would cut the statement mid-literal and leave an unterminated
    quote -- and a semicolon after it would then be reported as a comment
    semicolon that is not one. Without this test, a scanner that forgot about
    quotes passed every assertion in this module.
    """
    sql = (
        "SELECT 'a reading -- with a dash' AS reading, "
        "'it''s quoted' AS escaped;  -- a real comment; with a semicolon\n"
        "SELECT 2;\n")
    spans = list(_comment_spans(sql))
    assert len(spans) == 1, "scanner found %d comments, expected 1" % len(spans)
    assert spans[0][1].startswith("-- a real comment")
    assert [n for n, t in spans if ";" in t] == [1]

    body = _uncommented(sql)
    assert "a reading -- with a dash" in body, "the literal was eaten as a comment"
    assert "it''s quoted" in body, "the doubled-quote escape broke the scanner"
    assert "a real comment" not in body
    assert _statements(body) == ["SELECT 'a reading -- with a dash' AS reading, "
                                "'it''s quoted' AS escaped", "SELECT 2"]


def test_the_translator_refuses_rather_than_returning_a_plausible_zero():
    """A section rewritten into a shape this translator cannot run must FAIL."""
    with pytest.raises(Refused):
        _translate("SELECT @@session.time_zone", "1971-01-01 00:00:00")
    with pytest.raises(Refused):
        _translate("SELECT 1 FROM information_schema.COLUMNS", "1971-01-01 00:00:00")
    with pytest.raises(Refused):
        _translate("SELECT BINARY x FROM t", "1971-01-01 00:00:00")
    # And a positive control: the shapes it DOES handle come back translated.
    out = _translate("SELECT IF(a < @epoch_floor, 1, 0), CAST(b AS CHAR) FROM t WHERE id > @since_x",
                     "1971-01-01 00:00:00")
    assert "IIF(" in out and "AS TEXT" in out and "@" not in out


def test_sections_a_and_b_are_deliberately_out_of_scope_and_say_so():
    """Both files have an A and a B. This module runs neither -- assert that is

    a known exclusion rather than an omission nobody noticed.
    """
    for path in (POSITION_SQL, PRODUCER_SQL):
        sections = _sections(_text(path))
        assert "A" in sections and "B" in sections
        joined = " ".join(sections["A"] + sections["B"])
        assert any(tok.lower() in joined.lower() for tok in _REFUSED), (
            "%s's preflight no longer uses the constructs this module excludes, so "
            "it could now be covered -- extend the translator or drop this test" % path.name)
