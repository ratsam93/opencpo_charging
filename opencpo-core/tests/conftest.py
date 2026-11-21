"""Core tests run the real FastAPI app without a database (no lifespan is started).

Authentication dependencies run before any handler, so 401s need no database.
Handlers that do touch the database are given a tiny in-memory stand-in.
"""
import os
import sys

os.environ.setdefault("MANAGEMENT_API_KEY", "test-management-key")
os.environ.setdefault("API_KEY", "test-management-key")
os.environ.setdefault("PAYMENT_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("PG_HOST", "127.0.0.1")
os.environ.setdefault("PG_PORT", "1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

KEY = {"X-API-Key": "test-management-key"}


@pytest.fixture(scope="session")
def app():
    from api.main import app as _app
    return _app


@pytest.fixture()
def client(app):
    # raise_server_exceptions=False: a handler that needs the database answers 500
    # instead of raising, which is fine for "was authentication enforced?" checks.
    # client host 127.0.0.1: the rate limiter exempts loopback, so a long test run
    # is not throttled (the limiter itself is tested separately, later).
    return TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000))


class FakeConn:
    def __init__(self, store):
        self.store = store

    async def fetchrow(self, query, *args):
        return self.store.get("row")

    async def fetchval(self, *a, **k):
        return self.store.get("val", 0)

    async def fetch(self, *a, **k):
        return []

    async def execute(self, query, *args):
        self.store.setdefault("executed", []).append((query, args))


class FakeDB:
    def __init__(self):
        self.store = {}

    def _ctx(self):
        conn = FakeConn(self.store)

        class _C:
            async def __aenter__(_s):
                return conn

            async def __aexit__(_s, *a):
                return False
        return _C()

    def read(self):
        return self._ctx()

    def write(self):
        return self._ctx()


@pytest.fixture()
def fake_db(monkeypatch):
    import api.public as public
    db = FakeDB()
    monkeypatch.setattr(public, "db", db)
    started = []

    async def fake_start(session_id, cp_id, connector_id):
        started.append(session_id)

    monkeypatch.setattr(public, "_trigger_remote_start", fake_start)
    db.started = started
    return db
