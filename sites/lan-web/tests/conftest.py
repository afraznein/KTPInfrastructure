"""Fixtures for the route-level tests: a real signed session cookie and a
stand-in for app.db, so the JSON API can be exercised without MySQL."""
import base64
import json

import itsdangerous
import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app


class FakeDB:
    """Answers queries by SQL substring. An unmatched query raises rather than
    returning empty — an empty answer is what a broken probe looks like."""

    def __init__(self):
        self.rules = []
        self.writes = []
        self.txns = []

    def add(self, needle, result):
        """result may be a callable taking the query params."""
        self.rules.append((needle, result))
        return self

    def _match(self, sql, params):
        flat = " ".join(sql.split())
        for needle, result in self.rules:
            if needle in flat:
                return result(params) if callable(result) else result
        raise AssertionError(f"no fake rule for: {flat[:140]}")

    def query_one(self, sql, params=None):
        return self._match(sql, params)

    def query_all(self, sql, params=None):
        return self._match(sql, params)

    def execute(self, sql, params=None):
        self.writes.append((" ".join(sql.split()), params))
        return len(self.writes)

    def execute_all(self, statements):
        """One transaction in the app; here, the same writes list in order, and
        `txns` records the grouping — that is the property under test.

        Dispatches through db.execute rather than self.execute so a test that
        wraps the module function to model side effects still sees every write,
        whichever route wrote it."""
        stmts = list(statements)
        self.txns.append([" ".join(s.split()) for s, _ in stmts])
        first = None
        for sql, params in stmts:
            n = db.execute(sql, params)
            if first is None:
                first = n
        return first


@pytest.fixture
def fake_db(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(db, "query_one", f.query_one)
    monkeypatch.setattr(db, "query_all", f.query_all)
    monkeypatch.setattr(db, "execute", f.execute)
    monkeypatch.setattr(db, "execute_all", f.execute_all)
    return f


@pytest.fixture
def client():
    return TestClient(app)


def sign_in(client, discord_id, discord_name="nein"):
    """Mint the cookie SessionMiddleware would have written after OAuth, so the
    id arrives as the int the session really stores."""
    data = base64.b64encode(
        json.dumps({"discord_id": discord_id, "discord_name": discord_name}).encode()
    )
    signed = itsdangerous.TimestampSigner(settings.secret_key).sign(data).decode()
    client.cookies.set("session", signed)
