"""OCPP 2.0.1 handlers must hand the database real datetimes and JSON strings.

Live testing against a real core showed that every 2.0.1 handler which stored a
timestamp failed (asyncpg: "expected a datetime.date or datetime.datetime instance,
got 'str'") and that JSON columns received Python dicts. The stand-in connection
below rejects the same mistakes the real driver rejects.
"""
import asyncio
import json
from datetime import datetime, timezone

import pytest

from ocpp201.timeutil import parse_timestamp


# ── parse_timestamp ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "2026-11-21T12:29:39Z",
    "2026-11-21T12:29:39.123456Z",
    "2026-11-21T12:29:39+00:00",
    "2026-11-21T14:29:39+02:00",
    "2026-11-21T12:29:39",
    "2026-11-21T12:29:39.5",
])
def test_parse_timestamp_accepts_what_chargers_send(raw):
    ts = parse_timestamp(raw)
    assert isinstance(ts, datetime) and ts.tzinfo is not None
    assert (ts.year, ts.month, ts.day) == (2026, 11, 21)
    assert ts.astimezone(timezone.utc).hour == 12


@pytest.mark.parametrize("raw", [None, "", "not a time", 12345])
def test_parse_timestamp_falls_back_to_now(raw):
    before = datetime.now(timezone.utc)
    ts = parse_timestamp(raw)
    assert before <= ts <= datetime.now(timezone.utc)


def test_parse_timestamp_uses_given_default():
    fallback = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert parse_timestamp(None, default=fallback) == fallback


# ── handlers against a strict fake database ───────────────────────────────

class StrictConn:
    def __init__(self, log):
        self.log = log

    def _check(self, args):
        for a in args:
            if isinstance(a, (dict, list)):
                raise TypeError(f"asyncpg: jsonb parameter must be a str, got {type(a).__name__}")
            if isinstance(a, str) and len(a) >= 19 and a[4] == "-" and a[10] == "T":
                raise TypeError("asyncpg: expected a datetime.date or datetime.datetime instance, got 'str'")

    async def execute(self, query, *args):
        self._check(args)
        self.log.append((query, args))

    async def fetchrow(self, query, *args):
        self._check(args)
        self.log.append((query, args))
        if "RETURNING id::text as session_id" in query:
            return {"session_id": "11111111-1111-1111-1111-111111111111"}
        if "UPDATE ocpp.sessions SET" in query and "RETURNING" in query:
            return None
        return None


class StrictDB:
    def __init__(self):
        self.log = []

    def _ctx(self):
        conn = StrictConn(self.log)

        class _C:
            async def __aenter__(_s):
                return conn

            async def __aexit__(_s, *a):
                return False
        return _C()

    read = write = transaction = _ctx


class FakeRedis:
    async def set_charger(self, *a, **k): pass
    async def set_session(self, *a, **k): pass
    async def del_session(self, *a, **k): pass
    async def update_session_meter(self, *a, **k): pass


class FakeBus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)
        return "id"


@pytest.fixture()
def handler(monkeypatch):
    import ocpp201.handler as h
    import ocpp201.meter as m
    import ocpp201.security as s
    import ocpp201.transaction as t

    db = StrictDB()
    for mod in (h, m, s, t):
        monkeypatch.setattr(mod, "db", db)
        if hasattr(mod, "redis_state"):
            monkeypatch.setattr(mod, "redis_state", FakeRedis())
    obj = object.__new__(h.ChargePointHandler201)
    obj.cp_id = "CP-201"
    obj._simulated = False
    obj.event_bus = FakeBus()
    obj._active_transactions = {}

    async def no_cdr(session_id):
        return None
    obj._generate_cdr = no_cdr
    obj.db = db
    return obj


def run(coro):
    return asyncio.run(coro)


TS = "2026-11-21T12:29:39Z"


def test_status_notification_stores_a_datetime(handler):
    run(handler._on_status_notification(
        {"timestamp": TS, "connectorStatus": "Available", "evseId": 1, "connectorId": 1}))
    args = handler.db.log[-1][1]
    assert any(isinstance(a, datetime) for a in args)


def test_status_notification_without_timestamp(handler):
    run(handler._on_status_notification({"connectorStatus": "Occupied", "evseId": 1, "connectorId": 1}))
    assert any(isinstance(a, datetime) for a in handler.db.log[-1][1])


def test_transaction_lifecycle_started_updated_ended(handler):
    meter = [{"timestamp": TS, "sampledValue": [
        {"value": 1500, "measurand": "Energy.Active.Import.Register",
         "unitOfMeasure": {"unit": "Wh"}}]}]
    base = {"transactionInfo": {"transactionId": "T-1"}, "evse": {"id": 1, "connectorId": 1}, "seqNo": 0}
    run(handler._on_transaction_event({**base, "eventType": "Started", "timestamp": TS,
                                       "triggerReason": "Authorized", "idToken": {"idToken": "TAG", "type": "ISO14443"}}))
    # metadata (jsonb) is a JSON string, the start time a datetime
    start_args = next(a for q, a in handler.db.log if "INSERT INTO ocpp.sessions" in q)
    assert any(isinstance(a, datetime) for a in start_args)
    assert any(isinstance(a, str) and json.loads(a).get("transaction_id") == "T-1"
               for a in start_args if isinstance(a, str) and a.startswith("{"))
    run(handler._on_transaction_event({**base, "eventType": "Updated", "timestamp": TS, "seqNo": 1,
                                       "triggerReason": "MeterValuePeriodic", "meterValue": meter}))
    run(handler._on_transaction_event({**base, "eventType": "Ended", "timestamp": TS, "seqNo": 2,
                                       "triggerReason": "EVDeparted", "meterValue": meter}))
    assert any("INSERT INTO ocpp.meter_values" in q for q, _ in handler.db.log)
    assert any(e.type.name == "SESSION_START" for e in handler.event_bus.events)


def test_security_event_stores_datetime_and_json_string(handler):
    run(handler._on_security_event({"type": "StartupOfTheDevice", "timestamp": TS, "techInfo": "x"}))
    args = handler.db.log[-1][1]
    assert any(isinstance(a, datetime) for a in args)
    assert any(isinstance(a, str) and json.loads(a) == {"tech_info": "x"} for a in args if isinstance(a, str) and a.startswith("{"))


def test_message_log_writes_json_strings(handler):
    class Msg:
        action, unique_id, payload = "Heartbeat", "u1", {"a": 1}

    class Resp:
        payload = {"currentTime": TS}

    run(handler._log_message(Msg(), Resp(), 1.5))
    args = handler.db.log[-1][1]
    assert json.loads(args[3]) == {"a": 1} and json.loads(args[4]) == {"currentTime": TS}


# ── commands to a 2.0.1 charger ──────────────────────────────────────────

def test_command_to_connected_201_charger_explains_it_is_not_implemented(client, monkeypatch):
    import state.charger_registry as reg
    from tests.conftest import KEY
    monkeypatch.setattr(reg, "_handlers_201", {"CP-201": object()})
    r = client.post("/api/v1/chargers/CP-201/reset", json={"type": "Soft"}, headers=KEY)
    assert r.status_code == 501 and "2.0.1" in r.json()["detail"]


def test_command_to_unknown_charger_is_still_not_connected(client, monkeypatch):
    import state.charger_registry as reg
    from tests.conftest import KEY
    monkeypatch.setattr(reg, "_handlers_201", {})
    r = client.post("/api/v1/chargers/NOPE/reset", json={"type": "Soft"}, headers=KEY)
    assert r.status_code == 400 and "not connected" in r.json()["detail"]
