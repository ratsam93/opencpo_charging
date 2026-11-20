import asyncio, json, os, sys, time, collections, datetime, traceback
FARM = "/tmp/claude-0/-home-user-opencpo-charging/2936cd10-93d7-581c-a553-2f427033b420/scratchpad/t20/T16/farm"
MOCK_PORT, CP_PORT = 18150, 18151
os.environ.update({"OCPP16_URL": f"ws://127.0.0.1:{MOCK_PORT}/ocpp", "OCPP201_URL": "ws://127.0.0.1:18152/ocpp",
                   "HOST": "127.0.0.1", "PORT": str(CP_PORT), "DEMO_LOCATIONS": "false"})
os.chdir(FARM); sys.path.insert(0, FARM)
import httpx, uvicorn
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

scen = sys.argv[1]; RUN_SEC = float(sys.argv[2]) if len(sys.argv) > 2 else 35
counts = collections.Counter(); handshakes = []; tx = [0]; cps = set()

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
REPLY = {
 "BootNotification": lambda p: {"currentTime": now(), "interval": 300, "status": "Accepted"},
 "Heartbeat": lambda p: {"currentTime": now()},
 "StatusNotification": lambda p: {},
 "Authorize": lambda p: {"idTagInfo": {"status": "Accepted"}},
 "StartTransaction": lambda p: (tx.__setitem__(0, tx[0]+1), {"transactionId": tx[0], "idTagInfo": {"status": "Accepted"}})[1],
 "MeterValues": lambda p: {},
 "StopTransaction": lambda p: {"idTagInfo": {"status": "Accepted"}},
 "DataTransfer": lambda p: {"status": "Accepted"},
}

async def handler(ws):
    path = ws.request.path
    handshakes.append({"path": path, "offered": ws.request.headers.get("Sec-WebSocket-Protocol"), "selected": ws.subprotocol})
    cp = path.rstrip("/").split("/")[-1]; cps.add(cp)
    try:
        async for raw in ws:
            msg = json.loads(raw)
            mtype = msg[0]
            if mtype == 2:
                _, mid, action, payload = msg
                counts[action] += 1
                if action in REPLY:
                    await ws.send(json.dumps([3, mid, REPLY[action](payload)]))
                else:
                    counts["_NotImplementedSent"] += 1
                    await ws.send(json.dumps([4, mid, "NotImplemented", "mock", {}]))
            else:
                counts[f"_type{mtype}_from_charger"] += 1
    except ConnectionClosed:
        pass

def dump():
    with open(f"{os.path.dirname(FARM)}/mock_counts_{scen}.json", "w") as f:
        json.dump({"counts": dict(counts), "handshakes": handshakes, "cp_ids": sorted(cps)}, f, indent=1)

async def main():
    mock = await serve(handler, "127.0.0.1", MOCK_PORT, subprotocols=["ocpp1.6"])
    from control import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=CP_PORT, log_level="warning", access_log=False))
    st = asyncio.create_task(server.serve())
    base = f"http://127.0.0.1:{CP_PORT}"
    async with httpx.AsyncClient(base_url=base, timeout=10) as c:
        for _ in range(50):
            try:
                await c.get("/api/status"); break
            except Exception: await asyncio.sleep(0.2)
        r = await c.post(f"/api/scenarios/{scen}", json={"intensity": "low"})
        print("POST start:", r.status_code, r.text[:200], flush=True)
        t0 = time.monotonic(); samples = []
        while time.monotonic() - t0 < RUN_SEC:
            await asyncio.sleep(5)
            s = (await c.get("/api/status")).json()
            samples.append((round(time.monotonic()-t0), s["total_chargers"], s["connected"], s["charging"], s["scenario_active"]))
            print("STATUS t=%ds total=%s connected=%s charging=%s active=%s" % samples[-1], flush=True)
        chg = (await c.get("/api/chargers")).json()
        print("CHARGERS:", json.dumps(chg)[:400], flush=True)
        d = await c.delete("/api/scenarios/active")
        print("DELETE active:", d.status_code, d.text[:200], flush=True)
        await asyncio.sleep(2)
        ev = (await c.get("/api/events")).json()
        evs = ev if isinstance(ev, list) else ev.get("events", ev)
        bad = [e for e in evs if "error" in str(e).lower() or "traceback" in str(e).lower() or "fail" in str(e).lower() or "crash" in str(e).lower()]
        print("EVENTS total=%d error-like=%d" % (len(evs), len(bad)), flush=True)
        for e in bad[:15]: print("  EVT", json.dumps(e)[:300], flush=True)
    dump()
    print("MOCK counts:", dict(counts), flush=True)
    print("MOCK handshakes(first 3):", handshakes[:3], "distinct cp:", len(cps), flush=True)
    server.should_exit = True; await st
    mock.close(); await mock.wait_closed()

try:
    asyncio.run(main())
except Exception:
    traceback.print_exc(); dump(); print("DRIVER_EXCEPTION", flush=True)
