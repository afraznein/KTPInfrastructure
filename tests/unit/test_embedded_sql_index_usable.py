"""Every `BINARY a = BINARY b` outside sql/analytics must carry a plain twin too.

The analytics readers are held to this by test_analytics_sql_index_usable.py.
The same shape also lives in SQL that scripts build as Python strings, and in
sql/integrity. `BINARY` cannot use an index on a `_ci` column, so each test
needs `a = b AND` directly in front of it for the optimizer to narrow on.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
INTEGRITY = REPO / "sql" / "integrity"

BINARY_EQ = re.compile(r"BINARY\s+([\w.{}]+)\s*=\s*BINARY\s+([\w.{}]+)")


def strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def unadjacent_binary_equalities(text: str) -> list[str]:
    """BINARY tests not directly preceded by `a = b [COLLATE x] AND`.

    A twin elsewhere in the statement does not count: inside an OR it cannot
    narrow this test's range. COLLATE is allowed because a `_bin` operand
    against a `_ci` column needs it for the twin to reach the column's index.
    """
    missing = []
    for m in BINARY_EQ.finditer(text):
        a, b = m.group(1), m.group(2)
        twin = re.compile(
            rf"(?<![\w.]){re.escape(a)}\s*=\s*{re.escape(b)}"
            rf"(?:\s+COLLATE\s+\w+)?\s+AND\s+$", re.IGNORECASE)
        if not twin.search(text[:m.start()]):
            missing.append(f"{a} = {b}")
    return missing


def _placeholder(node: ast.AST) -> str:
    return "{" + re.sub(r"\W+", "_", ast.unparse(node)) + "}"


def string_literals(source: str) -> list[str]:
    """Each string literal's text; an f-string's fields become `{name}` tokens.

    Implicitly concatenated pieces arrive as one node, so a twin split across
    source lines is still adjacent here.
    """
    tree = ast.parse(source)
    parts = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
             for part in node.values}
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            out.append("".join(
                part.value if isinstance(part, ast.Constant) else _placeholder(part.value)
                for part in node.values))
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in parts):
            out.append(node.value)
    return out


def embedded_sql():
    for path in sorted(SCRIPTS.rglob("*.py")):
        texts = [strip_comments(s) for s in string_literals(path.read_text(encoding="utf-8"))]
        texts = [s for s in texts if BINARY_EQ.search(s)]
        if texts:
            yield path.relative_to(REPO).as_posix(), texts
    for path in sorted(INTEGRITY.glob("*.sql")):
        sql = strip_comments(path.read_text(encoding="utf-8"))
        if BINARY_EQ.search(sql):
            yield path.relative_to(REPO).as_posix(), [sql]


SOURCES = list(embedded_sql())


def test_the_scan_reaches_the_known_readers():
    names = {name for name, _ in SOURCES}
    for expected in ("scripts/report_service.py", "scripts/canary_evidence.py",
                     "scripts/lane_b_e2e.py", "scripts/report_scope.py",
                     "sql/integrity/position_corpus_integrity.sql"):
        assert expected in names, expected
    assert sum(len(BINARY_EQ.findall(t)) for _, texts in SOURCES for t in texts) > 30


@pytest.mark.parametrize("name,texts", SOURCES, ids=[name for name, _ in SOURCES])
def test_every_embedded_binary_test_has_an_adjacent_plain_twin(name, texts):
    assert [m for t in texts for m in unadjacent_binary_equalities(t)] == [], name


def test_fstring_fields_are_kept_as_comparable_operands():
    src = ('q = (f"WHERE match_id={sql_literal(m)} "\n'
           '     f"AND BINARY match_id=BINARY {sql_literal(m)}")\n'
           'r = f"WHERE BINARY x.match_id = BINARY {alias}.match_id"\n')
    texts = string_literals(src)
    assert unadjacent_binary_equalities(texts[0]) == []
    assert unadjacent_binary_equalities(texts[1]) == ["x.match_id = {alias}.match_id"]


def test_a_binary_test_with_a_distant_or_missing_twin_is_reported():
    assert unadjacent_binary_equalities(
        "WHERE BINARY m = BINARY {lit} OR BINARY p = BINARY {lit}") == ["m = {lit}", "p = {lit}"]
    assert unadjacent_binary_equalities(
        "WHERE m = x OR BINARY m = BINARY x") == ["m = x"]
    assert unadjacent_binary_equalities(
        "WHERE (m = {lit} AND BINARY m = BINARY {lit})\n"
        "   OR (p = {lit}\n       AND BINARY p = BINARY {lit})") == []
    assert unadjacent_binary_equalities(
        "WHERE km.m=s.m COLLATE utf8mb4_unicode_ci\n  AND BINARY km.m=BINARY s.m") == []
