from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
app = FastAPI(docs_url=None, redoc_url=None)
CHARGER = {"id": "CP-001", "name": "Demo Charger", "status": "Available", "lat": 52.37, "lng": 4.89,
           "connectors": [{"id": 1, "type": "CCS2", "status": "Available", "power_kw": 50}],
           "rate_per_kwh": 0.39, "site_id": "DEMO-SITE"}
@app.get("/health")
def health(): return {"status": "ok"}
@app.get("/api/v1/features")
def features(): return {}
@app.get("/api/v1/public/chargers/nearby")
def nearby(lat: float = 0, lng: float = 0, radius: float = 200): return {"chargers": [CHARGER], "count": 1}
@app.get("/api/v1/public/chargers/{cp_id}")
def public_charger(cp_id: str): return CHARGER
@app.get("/api/v1/chargers/{cp_id}")
def charger(cp_id: str): return CHARGER
@app.get("/api/v1/pricing/current")
def pricing(): return {"rate_per_kwh": 0.39, "currency": "EUR", "session_fee": 0}
@app.get("/api/v1/public/sessions/pending")
def pending(): return {"sessions": []}
@app.post("/api/v1/public/sessions")
async def create_session(request: Request):
    return {"session_id": "sess-0001", "status": "pending", "cp_id": "CP-001", "connector": 1}
@app.get("/api/v1/public/sessions/{sid}")
def get_session(sid: str): return {"session_id": sid, "status": "charging", "energy_kwh": 1.2, "cost": 0.47}
@app.post("/api/v1/public/sessions/{sid}/stop")
def stop(sid: str): return {"session_id": sid, "status": "stopping"}
@app.post("/api/v1/public/sessions/{sid}/cancel")
def cancel(sid: str): return {"session_id": sid, "status": "cancelled"}
@app.get("/api/v1/public/qr/{code}/lookup")
def qr(code: str): return {"cp_id": "CP-001", "connector": 1}
