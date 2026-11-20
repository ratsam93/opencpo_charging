# T05 client: exercises OCPP 1.6 server on 127.0.0.1:18040
import asyncio, json, uuid, datetime
import websockets
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, InvalidHandshake, ConnectionClosed
BASE = "ws://127.0.0.1:18040"
NOW = lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()

async def call(ws, action, payload):
    uid = str(uuid.uuid4())
    await ws.send(json.dumps([2, uid, action, payload]))
    raw = await asyncio.wait_for(ws.recv(), 10)
    return raw

async def main():
    cp = "CP-T05-1"
    print("== SEQUENCE on", BASE + "/ocpp/" + cp, "subprotocol=ocpp1.6")
    async with connect(f"{BASE}/ocpp/{cp}", subprotocols=["ocpp1.6"]) as ws:
        print("negotiated subprotocol:", ws.subprotocol)
        steps = [
            ("BootNotification", {"chargePointVendor": "TestVendor", "chargePointModel": "M1", "chargePointSerialNumber": "SN1", "firmwareVersion": "1.0"}),
            ("Heartbeat", {}),
            ("StatusNotification", {"connectorId": 1, "errorCode": "NoError", "status": "Available", "timestamp": NOW()}),
            ("Authorize", {"idTag": "GOOD123"}),
            ("Authorize", {"idTag": "NOPE999"}),
            ("StartTransaction", {"connectorId": 1, "idTag": "GOOD123", "meterStart": 1000, "timestamp": NOW()}),
            ("MeterValues", {"connectorId": 1, "transactionId": 1, "meterValue": [{"timestamp": NOW(), "sampledValue": [{"value": "1500", "measurand": "Energy.Active.Import.Register", "unit": "Wh"}]}]}),
            ("StopTransaction", {"transactionId": 1, "meterStop": 2000, "timestamp": NOW(), "reason": "Local"}),
            ("FooBar", {"x": 1}),
        ]
        for action, payload in steps:
            raw = await call(ws, action, payload)
            print(f"{action:18s} <- {raw}")
        print("-- malformed (non-JSON) frame --")
        await ws.send("not json")
        try:
            raw = await asyncio.wait_for(ws.recv(), 3)
            print("malformed <- ", raw)
        except asyncio.TimeoutError:
            print("malformed <- NO REPLY (3s timeout)")
        raw = await call(ws, "Heartbeat", {})
        print("Heartbeat after malformed <-", raw)

    print("== NO SUBPROTOCOL (client offers none)")
    try:
        async with connect(f"{BASE}/ocpp/CP-T05-2") as ws:
            print("handshake OK, negotiated subprotocol:", ws.subprotocol)
            try:
                raw = await asyncio.wait_for(ws.recv(), 5)
                print("recv:", raw)
            except ConnectionClosed as e:
                print("closed by server:", e.rcvd)
            try:
                raw = await call(ws, "Heartbeat", {})
                print("Heartbeat <-", raw)
            except Exception as e:
                print("Heartbeat exc:", type(e).__name__, e)
    except Exception as e:
        print("handshake exc:", type(e).__name__, e)

    print("== WRONG SUBPROTOCOL (client offers ocpp2.0.1 only)")
    try:
        async with connect(f"{BASE}/ocpp/CP-T05-3", subprotocols=["ocpp2.0.1"]) as ws:
            print("handshake OK, subprotocol:", ws.subprotocol)
    except Exception as e:
        print("handshake exc:", type(e).__name__, str(e)[:200])

    print("== UNREGISTERED CHARGER ID in path (never provisioned)")
    for path in ["/ocpp/UNREGISTERED-XYZ-777", "/ocpp/", "/"]:
        try:
            async with connect(f"{BASE}{path}", subprotocols=["ocpp1.6"]) as ws:
                raw = await call(ws, "BootNotification", {"chargePointVendor": "Unknown", "chargePointModel": "X"})
                print(f"path {path!r} accepted; BootNotification <- {raw}")
        except Exception as e:
            print(f"path {path!r} exc: {type(e).__name__} {str(e)[:200]}")

    print("== TLS: wss:// against plain port")
    try:
        import ssl
        ctx = ssl._create_unverified_context()
        async with connect("wss://127.0.0.1:18040/ocpp/CP-T05-4", subprotocols=["ocpp1.6"], ssl=ctx) as ws:
            print("wss connected (unexpected)")
    except Exception as e:
        print("wss exc:", type(e).__name__, str(e)[:200])

    print("== AUTH: connect with bogus Authorization header")
    try:
        async with connect(f"{BASE}/ocpp/CP-T05-5", subprotocols=["ocpp1.6"], additional_headers={"Authorization": "Basic bogus"}) as ws:
            raw = await call(ws, "Heartbeat", {})
            print("bogus-auth Heartbeat <-", raw)
    except Exception as e:
        print("bogus-auth exc:", type(e).__name__, str(e)[:200])

asyncio.run(main())
