import hashlib
import hmac
import json
import time

from tests.conftest import KEY

SECRET = "test-webhook-secret"
SID = "00000000-0000-0000-0000-000000000009"
PAID = {"session_id": SID, "status": "paid"}


def _sign(body: bytes, ts=None, secret=SECRET):
    ts = str(int(time.time()) if ts is None else ts)
    sig = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Webhook-Timestamp": ts, "X-Webhook-Signature": sig, "Content-Type": "application/json"}


def _post(client, body: dict, headers):
    raw = json.dumps(body).encode()
    return client.post("/api/payments/webhook", content=raw, headers=headers)


def _pending_session(fake_db):
    fake_db.store["row"] = {"id": SID, "cp_id": "CP1", "connector_id": 1, "payment_status": "pending"}


def test_unsigned_webhook_cannot_mark_a_session_paid(client, fake_db):
    """The live-test exploit: an anonymous POST used to mark any session paid and start a charge."""
    _pending_session(fake_db)
    r = client.post("/api/payments/webhook", json=PAID)
    assert r.status_code == 401
    assert fake_db.started == [] and "executed" not in fake_db.store


def test_wrong_signature_rejected(client, fake_db):
    _pending_session(fake_db)
    raw = json.dumps(PAID).encode()
    r = client.post("/api/payments/webhook", content=raw, headers=_sign(raw, secret="wrong"))
    assert r.status_code == 401 and fake_db.started == []


def test_tampered_body_rejected(client, fake_db):
    _pending_session(fake_db)
    headers = _sign(json.dumps({"session_id": SID, "status": "pending"}).encode())
    r = client.post("/api/payments/webhook", content=json.dumps(PAID).encode(), headers=headers)
    assert r.status_code == 401 and fake_db.started == []


def test_stale_timestamp_rejected(client, fake_db):
    _pending_session(fake_db)
    raw = json.dumps(PAID).encode()
    r = client.post("/api/payments/webhook", content=raw, headers=_sign(raw, ts=int(time.time()) - 3600))
    assert r.status_code == 401 and fake_db.started == []


def test_garbage_timestamp_rejected(client, fake_db):
    raw = json.dumps(PAID).encode()
    h = _sign(raw)
    h["X-Webhook-Timestamp"] = "not-a-number"
    assert client.post("/api/payments/webhook", content=raw, headers=h).status_code == 401


def test_valid_signature_marks_paid_and_starts_charging(client, fake_db):
    _pending_session(fake_db)
    raw = json.dumps(PAID).encode()
    r = client.post("/api/payments/webhook", content=raw, headers=_sign(raw))
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert fake_db.started == [SID]
    assert any("payment_status" in q for q, _ in fake_db.store["executed"])


def test_management_key_also_accepted(client, fake_db):
    _pending_session(fake_db)
    r = client.post("/api/payments/webhook", json=PAID, headers=KEY)
    assert r.status_code == 200 and fake_db.started == [SID]


def test_unknown_status_rejected_even_when_signed(client, fake_db):
    """Internal states (e.g. remote_start_failed) cannot be forced from outside."""
    _pending_session(fake_db)
    raw = json.dumps({"session_id": SID, "status": "remote_start_failed"}).encode()
    r = client.post("/api/payments/webhook", content=raw, headers=_sign(raw))
    assert r.status_code == 400 and "executed" not in fake_db.store


def test_without_a_configured_secret_only_the_key_works(client, fake_db, monkeypatch):
    monkeypatch.delenv("PAYMENT_WEBHOOK_SECRET")
    _pending_session(fake_db)
    raw = json.dumps(PAID).encode()
    assert client.post("/api/payments/webhook", content=raw, headers=_sign(raw)).status_code == 401
    assert client.post("/api/payments/webhook", json=PAID, headers=KEY).status_code == 200


def test_already_paid_session_is_not_started_twice(client, fake_db):
    fake_db.store["row"] = {"id": SID, "cp_id": "CP1", "connector_id": 1, "payment_status": "paid"}
    raw = json.dumps(PAID).encode()
    client.post("/api/payments/webhook", content=raw, headers=_sign(raw))
    assert fake_db.started == []
