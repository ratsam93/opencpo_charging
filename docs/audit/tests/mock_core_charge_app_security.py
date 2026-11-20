"""Mock OCPP core for T11 security checks. Logs every request with headers to a JSONL file."""
import json, time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

LOG = "/tmp/claude-0/-home-user-opencpo-charging/2936cd10-93d7-581c-a553-2f427033b420/scratchpad/t20/T11/mock_core.jsonl"
app = FastAPI(docs_url=None, redoc_url=None)

@app.middleware("http")
async def log_all(request: Request, call_next):
    body = (await request.body()).decode("utf-8", "replace")
    rec = {"ts": time.time(), "method": request.method, "path": request.url.path,
           "query": str(request.url.query), "headers": dict(request.headers), "body": body[:500]}
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return await call_next(request)

@app.get("/api/v1/features")
async def features():
    return {"flags": {}, "details": []}

@app.get("/api/v1/public/cert/identify")
async def cert_identify(serial: str = ""):
    if serial == "ABC123":
        return {"id": "drv-victim-1", "email": "victim@example.test", "name": "Victim Driver",
                "pricing_tier": "fleet", "group_id": 7, "cert_serial": "ABC123",
                "cert_expires_at": "2099-01-01T00:00:00+00:00"}
    return JSONResponse({"detail": "not found"}, status_code=404)

@app.get("/api/v1/public/sessions/pending")
async def pending():
    return JSONResponse({"detail": "none"}, status_code=404)

@app.get("/api/v1/public/sessions/{sid}")
async def get_session(sid: str):
    if sid == "BOOM-SESSION":
        return PlainTextResponse("internal failure SECRET-TRACE line 42 db=postgres://u:p@10.0.0.5/core", status_code=500)
    return {"id": sid, "status": "Charging", "owner_driver_id": "drv-victim-1",
            "driver_phone": "+31600000001", "energy_kwh": 12.3, "amount": 9.99}

@app.post("/api/v1/public/sessions/{sid}/stop")
async def stop(sid: str):
    if sid == "BOOM-SESSION":
        return JSONResponse({"detail": "core fault SECRET-TRACE stack: /srv/core/api.py:99"}, status_code=500)
    return {"ok": True, "stopped": sid}

@app.post("/api/v1/public/sessions/{sid}/cancel")
async def cancel(sid: str):
    return {"ok": True, "cancelled": sid}

@app.get("/api/v1/public/sessions/{sid}/pdf")
async def pdf(sid: str):
    from fastapi.responses import Response
    return Response(content=b"%PDF-1.4 mock", media_type="application/pdf")

@app.post("/api/v1/public/account/login")
async def login(request: Request):
    return {"token": "mock-core-token-xyz", "account": {"id": "drv-victim-1", "email": "victim@example.test"}}

@app.get("/api/v1/chargers/{cp}")
async def charger(cp: str):
    return {"cp_id": cp, "connectors": [], "live": {}}
