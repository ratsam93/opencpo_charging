"""Tiny mock of OCPP Core admin API for T08 testing. Binds 127.0.0.1:18071."""
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

SECRET = "k"
app = FastAPI()
NOW = datetime.now(timezone.utc).isoformat()
USER = {"id": 1, "email": "admin@example.com", "name": "Admin", "role": "admin"}
CHARGERS = [{
    "id": "CP001", "name": "Bay 1", "status": "Available", "vendor": "Acme",
    "model": "AC22", "location": "Lot A", "last_heartbeat": NOW, "tariff_id": 1,
    "connectors": [{"id": 1, "type": "Type2", "status": "Available", "power_kw": 22}],
}]

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/api/v1/admin/auth/login")
async def login(request: Request):
    body = await request.json()
    if body.get("password") != "pw":
        return JSONResponse({"detail": "Invalid email or password."}, status_code=401)
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode({**USER, "sub": "1", "exp": exp}, SECRET, algorithm="HS256")
    return {"token": token, "user": USER}

@app.get("/api/v1/admin/auth/me")
async def me():
    return USER

@app.get("/api/v1/admin/setup/status")
async def setup_status():
    return {"complete": True, "steps": {}}

@app.get("/api/v1/chargers")
async def chargers():
    return {"chargers": CHARGERS, "total": len(CHARGERS)}

@app.get("/api/v1/sessions")
async def sessions():
    return {"sessions": [], "total": 0}

@app.get("/api/v1/tariffs")
async def tariffs():
    return {"tariffs": [{"id": 1, "name": "Standard", "currency": "EUR",
                         "price_per_kwh": 0.30, "price_per_session": 0.0,
                         "price_per_minute": 0.0, "active": True}]}

@app.get("/api/v1/pki/stats")
async def pki_stats():
    return {"total_certs": 0, "active": 0, "revoked": 0, "expiring_30d": 0}

@app.get("/api/v1/pki/ca-hierarchy")
async def pki_hier():
    return {"roots": []}

@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all(path: str):
    return {}
