"""Test fixtures: the app talks to an in-process mock Core API (no network)."""
import os
import sys

import httpx
import jwt
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)  # the app uses relative paths (skins/, static/, templates/)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")
os.environ.setdefault("MANAGEMENT_API_KEY", "mgmt-test-key")

import config  # noqa: E402

mock_core = FastAPI()
CALLS: list[dict] = []
STATE = {"fail": False, "duplicate_of_other": None}


def _need_key(request: Request):
    """Real core: GET/stop/cancel/pdf of a session need the management key."""
    if request.headers.get("x-api-key") != "mgmt-test-key":
        raise HTTPException(401, "Invalid or missing API key")


def _log(request: Request):
    CALLS.append({"method": request.method, "path": request.url.path,
                  "x_api_key": request.headers.get("x-api-key"),
                  "x_client_cert_serial": request.headers.get("x-client-cert-serial")})


@mock_core.post("/api/v1/public/sessions")
async def create(request: Request):
    _log(request)
    body = await request.json()
    if STATE["duplicate_of_other"]:
        # Real core's duplicate guard answers with the EXISTING session in this shape
        # (observed live): no created_at, no phone/email.
        return {"session_id": STATE["duplicate_of_other"], "status": "waiting",
                "message": "Charger is starting, please try again in 10 seconds."}
    return {"session_id": "S-1", "cp_id": body.get("cp_id"), "connector_id": 1,
            "payment_status": "pending", "rate_kwh": 0.35, "pricing_tier": "public",
            "created_at": "2026-11-21T12:00:00+00:00"}


@mock_core.api_route("/api/v1/public/cert-setup/{path:path}", methods=["GET", "POST"])
async def cert_setup(path: str, request: Request):
    _log(request)
    return {"status": "ok"}


@mock_core.get("/api/v1/public/sessions/pending")
async def pending(request: Request):
    _log(request)
    raise HTTPException(404)


@mock_core.get("/api/v1/public/sessions/{sid}")
async def get_session(sid: str, request: Request):
    _log(request)
    _need_key(request)
    if STATE["fail"]:
        raise HTTPException(500, "SECRET-TRACE /srv/core/api.py:99")
    return {"id": sid, "driver_id": "drv-1", "phone": "+31600000000", "amount": "12.30"}


@mock_core.post("/api/v1/public/sessions/{sid}/stop")
async def stop(sid: str, request: Request):
    _log(request)
    _need_key(request)
    return {"ok": True, "stopped": sid}


@mock_core.post("/api/v1/public/sessions/{sid}/cancel")
async def cancel(sid: str, request: Request):
    _log(request)
    _need_key(request)
    return {"ok": True, "cancelled": sid}


@mock_core.get("/api/v1/public/sessions/{sid}/pdf")
async def pdf(sid: str, request: Request):
    _log(request)
    _need_key(request)
    return {"pdf": sid}


@mock_core.get("/api/v1/chargers/{cp}")
async def charger(cp: str, request: Request):
    _log(request)
    return {"connectors": [{"connector_id": 1, "status": "Available"}]}


@mock_core.get("/api/v1/public/cert/identify")
async def identify(serial: str, request: Request):
    _log(request)
    if serial == "ABC123":
        return {"id": "drv-victim", "email": "victim@example.test", "name": "Victim Driver"}
    raise HTTPException(404)


_RealClient = httpx.AsyncClient


class _MockClient(_RealClient):
    def __init__(self, *a, **kw):
        kw["transport"] = httpx.ASGITransport(app=mock_core)
        super().__init__(*a, **kw)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    CALLS.clear()
    STATE["fail"] = False
    STATE["duplicate_of_other"] = None
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    import core.api
    monkeypatch.setattr(core.api, "CORE_API_KEY", "mgmt-test-key")
    yield


@pytest.fixture
def calls():
    return CALLS


@pytest.fixture
def state():
    return STATE


@pytest.fixture
def make_client():
    from main import app

    def _make():
        return TestClient(app, base_url="https://testserver")
    return _make


def account_token(account_id: str) -> str:
    return jwt.encode({"id": account_id, "email": f"{account_id}@example.test"},
                      config.JWT_SECRET, algorithm="HS256")
