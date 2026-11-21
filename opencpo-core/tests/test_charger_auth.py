"""OCPP charger authentication: unit tests, real WebSocket connections, management API."""
import asyncio
import base64
import ipaddress

import bcrypt
import pytest
import websockets
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from security import charger_auth
from security.charger_auth import ChargerAuthenticator, cp_id_from_path, parse_basic
from tests.conftest import KEY


def basic(user, password):
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


class CredDB:
    """In-memory stand-in for ocpp.charger_credentials."""

    def __init__(self):
        self.rows = {}

    def _ctx(self):
        db = self

        class Conn:
            async def fetchrow(_s, query, *a):
                if "SELECT password_hash" in query:
                    r = db.rows.get(a[0])
                    return {"password_hash": r["hash"]} if r and not r["revoked"] else None
                if "UPDATE ocpp.charger_credentials SET revoked_at" in query:
                    r = db.rows.get(a[0])
                    if r and not r["revoked"]:
                        r["revoked"] = True
                        return {"charge_point": a[0]}
                return None

            async def fetch(_s, query, *a):
                return [{"charge_point": k, "created_at": 1, "updated_at": 1,
                         "revoked_at": 1 if v["revoked"] else None} for k, v in sorted(db.rows.items())]

            async def execute(_s, query, *a):
                db.rows[a[0]] = {"hash": a[1], "revoked": False}

        class C:
            async def __aenter__(_s):
                return Conn()

            async def __aexit__(_s, *x):
                return False
        return C()

    read = write = _ctx


def make_auth(db=None, **kw):
    return ChargerAuthenticator(db or CredDB(), **kw)


async def provision(auth, cp_id, password="a-long-enough-secret"):
    await auth.set_password(cp_id, password)
    return password


def run(coro):
    return asyncio.run(coro)


# ── helpers ───────────────────────────────────────────────────────────────

def test_parse_basic():
    assert parse_basic(basic("CP1", "pw")) == ("CP1", "pw")
    assert parse_basic(basic("CP1", "pa:ss:word")) == ("CP1", "pa:ss:word")
    for bad in (None, "", "Bearer x", "Basic", "Basic !!!notbase64", "Basic " + base64.b64encode(b"nocolon").decode()):
        assert parse_basic(bad) is None


@pytest.mark.parametrize("path,expected", [
    ("/ocpp/CP001", "CP001"), ("/CP001", "CP001"), ("/ocpp/CP001?x=1", "CP001"),
    ("/ocpp/CP001/", "CP001"), ("/", ""), ("", ""), ("/ocpp/", "ocpp"),
])
def test_cp_id_from_path(path, expected):
    assert cp_id_from_path(path) == expected


# ── authenticator ─────────────────────────────────────────────────────────

def test_unauthenticated_unknown_wrong_and_valid():
    async def go():
        auth = make_auth()
        pw = await provision(auth, "CP1")
        d = await auth.authenticate("CP1", None, "203.0.113.9")
        assert (d.allowed, d.status) == (False, 401)
        assert (await auth.authenticate("CP1", basic("CP1", "wrong"), "203.0.113.9")).status == 401
        assert (await auth.authenticate("UNKNOWN", basic("UNKNOWN", pw), "203.0.113.9")).status == 401
        assert (await auth.authenticate("CP1", basic("OTHER", pw), "203.0.113.9")).status == 401   # user must be the id
        ok = await auth.authenticate("CP1", basic("CP1", pw), "203.0.113.9")
        assert ok.allowed and ok.method == "password"
    run(go())


def test_password_with_colon_and_revocation():
    async def go():
        auth = make_auth()
        pw = await provision(auth, "CP1", "pass:with:colons-1234")
        assert (await auth.authenticate("CP1", basic("CP1", pw), "203.0.113.9")).allowed
        assert await auth.revoke("CP1") is True
        assert await auth.revoke("CP1") is False
        assert (await auth.authenticate("CP1", basic("CP1", pw), "203.0.113.9")).status == 401
        pw2 = await provision(auth, "CP1", "a-brand-new-secret-123")     # rotation re-activates
        assert (await auth.authenticate("CP1", basic("CP1", pw2), "203.0.113.9")).allowed
        assert not (await auth.authenticate("CP1", basic("CP1", pw), "203.0.113.9")).allowed  # old password dead
    run(go())


@pytest.mark.parametrize("cp_id", ["", "a/b", "x" * 65, "has space", "tab\t", "ü", "CP%2F1"])
def test_invalid_ids_are_rejected_with_400(cp_id):
    async def go():
        auth = make_auth()
        d = await auth.authenticate(cp_id, basic(cp_id, "pw"), "203.0.113.9")
        assert (d.allowed, d.status) == (False, 400)
    run(go())


def test_wrong_passwords_still_run_bcrypt(monkeypatch):
    """Unknown ids must cost the same as wrong passwords (no id enumeration by timing)."""
    calls = []
    real = bcrypt.checkpw
    monkeypatch.setattr(bcrypt, "checkpw", lambda p, h: calls.append(1) or real(p, h))

    async def go():
        auth = make_auth()
        await auth.authenticate("NOPE", basic("NOPE", "x"), "203.0.113.9")
    run(go())
    assert calls == [1]


def test_trusted_networks_and_hosts():
    async def resolver(host):
        return {ipaddress.ip_address("172.20.0.7")} if host == "charger-farm" else set()

    async def go():
        auth = make_auth(trusted_cidrs=["100.64.0.0/10"], trusted_hosts=["charger-farm"], resolver=resolver)
        d = await auth.authenticate("ANY-ID", None, "100.101.102.103")
        assert d.allowed and d.method == "trusted-network"
        assert (await auth.authenticate("ANY-ID", None, "172.20.0.7")).allowed          # resolved host
        assert (await auth.authenticate("ANY-ID", None, "::ffff:100.64.0.9")).allowed   # IPv4-mapped IPv6
        assert (await auth.authenticate("ANY-ID", None, "172.20.0.8")).status == 401     # neighbour is not trusted
        assert (await auth.authenticate("ANY-ID", None, "198.51.100.1")).status == 401
        # trust does not excuse a malformed id
        assert (await auth.authenticate("", None, "100.101.102.103")).status == 400
    run(go())


def test_mode_off_allows_everything():
    async def go():
        assert (await make_auth(mode="off").authenticate("", None, "203.0.113.9")).allowed
    run(go())


def test_client_certificate_must_match_the_id():
    async def go():
        auth = make_auth()
        ok = await auth.authenticate("CP1", None, "203.0.113.9", cert_cn="CP1")
        assert ok.allowed and ok.method == "client-certificate"
        bad = await auth.authenticate("CP1", None, "203.0.113.9", cert_cn="CP2")
        assert (bad.allowed, bad.status) == (False, 403)
    run(go())


def test_repeated_failures_are_throttled():
    async def go():
        auth = make_auth()
        pw = await provision(auth, "CP1")
        for _ in range(10):
            assert (await auth.authenticate("CP1", basic("CP1", "wrong"), "203.0.113.50")).status == 401
        # the 11th attempt is refused even with the right password
        assert (await auth.authenticate("CP1", basic("CP1", pw), "203.0.113.50")).status == 429
        # another address is unaffected
        assert (await auth.authenticate("CP1", basic("CP1", pw), "203.0.113.51")).allowed
    run(go())


# ── real WebSocket connections ────────────────────────────────────────────

async def _serve(server_cls, subprotocol, auth, monkeypatch):
    monkeypatch.setattr(charger_auth, "authenticator", auth)
    seen = []

    async def on_connect(cp_id, ws, *rest):
        seen.append(cp_id)
        await ws.send("hello " + cp_id)
        async for _ in ws:
            pass

    async def on_disconnect(cp_id):
        return None

    server = server_cls(on_connect, on_disconnect)
    task = asyncio.create_task(server.serve("127.0.0.1", 0))
    for _ in range(100):
        if server._server is not None:
            break
        await asyncio.sleep(0.02)
    port = server._server.sockets[0].getsockname()[1]
    return server, task, port, seen


def _servers():
    from ocpp16.server import OCPP16Server
    from ocpp201.server import OCPP201Server
    return [(OCPP16Server, "ocpp1.6"), (OCPP201Server, "ocpp2.0.1")]


@pytest.mark.parametrize("idx", [0, 1])
def test_websocket_connections(idx, monkeypatch):
    server_cls, sub = _servers()[idx]

    async def go():
        auth = make_auth()
        pw = await provision(auth, "CP1")
        server, task, port, seen = await _serve(server_cls, sub, auth, monkeypatch)
        url = lambda path: f"ws://127.0.0.1:{port}{path}"  # noqa: E731
        try:
            # 1. no credentials -> HTTP 401 before the handshake completes
            with pytest.raises(InvalidStatus) as e:
                async with connect(url("/ocpp/CP1"), subprotocols=[sub]):
                    pass
            assert e.value.response.status_code == 401
            assert "Basic" in e.value.response.headers["WWW-Authenticate"]
            # 2. wrong password, unknown charger
            for user, pwd, path in (("CP1", "nope", "/ocpp/CP1"), ("GHOST", pw, "/ocpp/GHOST")):
                with pytest.raises(InvalidStatus) as e:
                    async with connect(url(path), subprotocols=[sub],
                                       additional_headers={"Authorization": basic(user, pwd)}):
                        pass
                assert e.value.response.status_code == 401
            # 3. empty id (used to create a charge point called "")
            with pytest.raises(InvalidStatus) as e:
                async with connect(url("/"), subprotocols=[sub],
                                   additional_headers={"Authorization": basic("", pw)}):
                    pass
            assert e.value.response.status_code == 400
            assert seen == [], "a refused charger must never reach the message handler"
            # 4. valid credentials
            async with connect(url("/ocpp/CP1"), subprotocols=[sub],
                               additional_headers={"Authorization": basic("CP1", pw)}) as ws:
                assert await ws.recv() == "hello CP1"
                # 5. revoking disconnects a live charger
                await auth.revoke("CP1")
                assert await server.disconnect("CP1") is True
                with pytest.raises(ConnectionClosed) as closed:
                    await asyncio.wait_for(ws.recv(), 3)
                assert closed.value.rcvd.code == 1008
            # ...and it cannot come back
            with pytest.raises(InvalidStatus):
                async with connect(url("/ocpp/CP1"), subprotocols=[sub],
                                   additional_headers={"Authorization": basic("CP1", pw)}):
                    pass
        finally:
            await server.stop()
            task.cancel()
    run(go())


def test_trusted_network_connects_without_credentials(monkeypatch):
    from ocpp16.server import OCPP16Server

    async def go():
        auth = make_auth(trusted_cidrs=["127.0.0.0/8"])
        server, task, port, seen = await _serve(OCPP16Server, "ocpp1.6", auth, monkeypatch)
        try:
            async with connect(f"ws://127.0.0.1:{port}/ocpp/SIM-1", subprotocols=["ocpp1.6"]) as ws:
                assert await ws.recv() == "hello SIM-1"
        finally:
            await server.stop()
            task.cancel()
    run(go())


# ── management API ────────────────────────────────────────────────────────

@pytest.fixture()
def api_auth(monkeypatch):
    auth = make_auth()
    monkeypatch.setattr(charger_auth, "authenticator", auth)
    disconnects = []

    async def fake_disconnect(cp_id, *a, **k):
        disconnects.append(cp_id)
        return True

    import state.charger_registry as reg
    monkeypatch.setattr(reg, "disconnect", fake_disconnect)
    auth.disconnects = disconnects
    return auth


def test_api_create_rotate_list_revoke(client, api_auth):
    r = client.post("/api/v1/charger-credentials/CP9", headers=KEY)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    pw = r.json()["password"]
    assert len(pw) >= 32
    assert run(api_auth.authenticate("CP9", basic("CP9", pw), "203.0.113.1")).allowed
    # the list never contains secrets or hashes
    listing = client.get("/api/v1/charger-credentials", headers=KEY).json()["credentials"]
    assert [c["charge_point"] for c in listing] == ["CP9"]
    assert "password" not in str(listing) and "hash" not in str(listing)
    # rotation invalidates the old password
    pw2 = client.post("/api/v1/charger-credentials/CP9", headers=KEY).json()["password"]
    assert pw2 != pw
    assert not run(api_auth.authenticate("CP9", basic("CP9", pw), "203.0.113.2")).allowed
    # revoke disconnects the live charger
    r = client.delete("/api/v1/charger-credentials/CP9", headers=KEY)
    assert r.status_code == 200 and r.json()["disconnected"] is True and api_auth.disconnects == ["CP9"]
    assert client.delete("/api/v1/charger-credentials/CP9", headers=KEY).status_code == 404


def test_api_validates_input(client, api_auth):
    assert client.post("/api/v1/charger-credentials/CP9", json={"password": "short"}, headers=KEY).status_code == 422
    assert client.post("/api/v1/charger-credentials/bad id", headers=KEY).status_code in (404, 422)
    assert client.post("/api/v1/charger-credentials/" + "x" * 65, headers=KEY).status_code == 422
    ok = client.post("/api/v1/charger-credentials/CP9", json={"password": "my-own-long-password-1"}, headers=KEY)
    assert ok.status_code == 200 and ok.json()["password"] == "my-own-long-password-1"
