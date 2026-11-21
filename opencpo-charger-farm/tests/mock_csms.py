"""Minimal mock CSMS for OCPP 1.6 and 2.0.1 (raw JSON-RPC over websockets).

Counts every incoming CALL by action. Usable from tests or standalone:
    python tests/mock_csms.py PORT
"""

import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import websockets


def _now():
    return datetime.now(timezone.utc).isoformat()


class MockCSMS:
    def __init__(self, port: int, host: str = "127.0.0.1"):
        self.port = port
        self.host = host
        self.counts: Counter = Counter()
        self.subprotocols: list = []
        self.cp_ids: set = set()
        self.first_seen: dict = {}
        self._tx = 0
        self._server = None
        self._t0 = time.time()

    def _reply(self, action: str, payload: dict, v201: bool) -> dict:
        if action == "BootNotification":
            return {"status": "Accepted", "currentTime": _now(), "interval": 30}
        if action == "Heartbeat":
            return {"currentTime": _now()}
        if action == "Authorize":
            if v201:
                return {"idTokenInfo": {"status": "Accepted"}}
            return {"idTagInfo": {"status": "Accepted"}}
        if action == "StartTransaction":
            self._tx += 1
            return {"transactionId": self._tx, "idTagInfo": {"status": "Accepted"}}
        if action == "StopTransaction":
            return {"idTagInfo": {"status": "Accepted"}}
        if action == "TransactionEvent":
            return {}
        return {}  # StatusNotification, MeterValues, DataTransfer(...), etc.

    async def _handler(self, ws):
        sub = ws.subprotocol
        v201 = sub == "ocpp2.0.1"
        self.subprotocols.append(sub)
        path = getattr(getattr(ws, "request", None), "path", "") or ""
        self.cp_ids.add(path.rsplit("/", 1)[-1])
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg[0] == 2:
                    _, uid, action, payload = msg
                    self.counts[action] += 1
                    self.first_seen.setdefault(action, round(time.time() - self._t0, 1))
                    await ws.send(json.dumps([3, uid, self._reply(action, payload, v201)]))
        except websockets.ConnectionClosed:
            pass

    async def start(self):
        self._server = await websockets.serve(
            self._handler, self.host, self.port,
            subprotocols=["ocpp1.6", "ocpp2.0.1"],
        )
        return self

    async def stop(self):
        self._server.close()
        await self._server.wait_closed()


if __name__ == "__main__":
    async def _main():
        csms = await MockCSMS(int(sys.argv[1])).start()
        try:
            while True:
                await asyncio.sleep(10)
                print(dict(csms.counts), flush=True)
        finally:
            await csms.stop()
    asyncio.run(_main())
