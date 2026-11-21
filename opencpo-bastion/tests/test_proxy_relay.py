"""Relay, reconnect and mTLS tests for gateway/proxy.py (ports 19170-19179, loopback only)."""
import asyncio
import ssl
from types import SimpleNamespace

import pytest
import websockets

from gateway.config import GatewayConfig
from gateway.proxy import OCPPProxy, _request_path, get_message_buffer
from tests import _pki

UP, P16, P201 = 19170, 19171, 19172
FRAME = '[2,"1","Heartbeat",{}]'


def make_cfg(**kw):
    cfg = GatewayConfig(core_api_url=f"http://127.0.0.1:{UP}", **kw)
    cfg.proxy_ports.ocpp16, cfg.proxy_ports.ocpp201 = P16, P201
    return cfg


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 30))


async def serve_upstream(handler):
    return await websockets.serve(handler, "127.0.0.1", UP, subprotocols=["ocpp1.6"])


def test_websockets_version_reported():
    print("websockets", websockets.__version__)


def test_request_path_both_apis():
    new = SimpleNamespace(request=SimpleNamespace(path="/ocpp/A"))
    old = SimpleNamespace(path="/ocpp/B")
    assert _request_path(new, None) == "/ocpp/A"
    assert _request_path(old, "/ocpp/B") == "/ocpp/B"      # legacy path arg
    assert _request_path(old, None) == "/ocpp/B"           # legacy ws.path


def test_relay_round_trip():
    seen_paths = []

    async def scenario():
        async def echo(ws):
            seen_paths.append(_request_path(ws))
            async for m in ws:
                await ws.send("echo:" + m)

        up = await serve_upstream(echo)
        proxy = OCPPProxy(make_cfg(), bind="127.0.0.1")
        await proxy.start()
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{P16}/ocpp/CP1", subprotocols=["ocpp1.6"]
            ) as cp:
                await cp.send(FRAME)
                assert await cp.recv() == "echo:" + FRAME
                assert proxy.active_chargers() == ["CP1"]
        finally:
            await proxy.stop()
            up.close()
            await up.wait_closed()

    run(scenario())
    assert seen_paths == ["/ocpp/1.6/CP1"]
    assert any(m.charger_id == "CP1" and m.direction == "down" for m in get_message_buffer())


def test_upstream_drop_reconnects_and_keeps_charger():
    conns = []

    async def scenario():
        async def flaky(ws):
            conns.append(ws)
            if len(conns) == 1:
                await ws.recv()
                await ws.close()
                return
            async for m in ws:
                await ws.send("echo:" + m)

        up = await serve_upstream(flaky)
        proxy = OCPPProxy(make_cfg(), bind="127.0.0.1")
        proxy.conn_kwargs = dict(initial_backoff=0.1, max_backoff=0.2, max_attempts=20)
        await proxy.start()
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{P16}/ocpp/CP2", subprotocols=["ocpp1.6"]
            ) as cp:
                await cp.send("first")           # upstream drops after this one
                await asyncio.sleep(0.05)
                await cp.send(FRAME)             # buffered / sent after reconnect
                assert await asyncio.wait_for(cp.recv(), 10) == "echo:" + FRAME
                assert len(conns) == 2
        finally:
            await proxy.stop()
            up.close()
            await up.wait_closed()

    run(scenario())


def test_charger_close_closes_upstream():
    closed = asyncio.Event

    async def scenario():
        ev = asyncio.Event()

        async def h(ws):
            try:
                async for _ in ws:
                    pass
            finally:
                ev.set()

        up = await serve_upstream(h)
        proxy = OCPPProxy(make_cfg(), bind="127.0.0.1")
        await proxy.start()
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{P16}/ocpp/CP3", subprotocols=["ocpp1.6"]
            ) as cp:
                await cp.send(FRAME)
                await asyncio.sleep(0.2)
            await asyncio.wait_for(ev.wait(), 5)     # upstream saw the close
            await asyncio.sleep(0.1)
            assert proxy.active_chargers() == []
        finally:
            await proxy.stop()
            up.close()
            await up.wait_closed()

    run(scenario())


def test_reconnect_exhausted_closes_charger():
    async def scenario():
        proxy = OCPPProxy(make_cfg(), bind="127.0.0.1")   # nothing listens on UP
        proxy.conn_kwargs = dict(initial_backoff=0.05, max_backoff=0.05, max_attempts=2)
        await proxy.start()
        try:
            async with websockets.connect(
                f"ws://127.0.0.1:{P16}/ocpp/CP4", subprotocols=["ocpp1.6"]
            ) as cp:
                with pytest.raises(websockets.exceptions.ConnectionClosed) as ei:
                    await asyncio.wait_for(cp.recv(), 10)
                code = ei.value.rcvd.code
                assert code == 1011
        finally:
            await proxy.stop()

    run(scenario())


# ── listener security ────────────────────────────────────────────────────────

def test_refuses_nonloopback_without_tls():
    proxy = OCPPProxy(make_cfg(), bind="0.0.0.0")
    with pytest.raises(RuntimeError, match="allow_insecure"):
        run(proxy.start())


def test_allow_insecure_opt_in_starts(caplog):
    async def scenario():
        proxy = OCPPProxy(make_cfg(allow_insecure=True), bind="0.0.0.0")
        await proxy.start()
        await proxy.stop()

    with caplog.at_level("WARNING"):
        run(scenario())
    assert "INSECURE LISTENER" in caplog.text


@pytest.fixture
def pki(tmp_path):
    ca_key, ca = _pki.make_ca()
    paths = {"ca": _pki.write_cert(tmp_path, "ca", ca)}
    paths["srv"] = _pki.write_pair(tmp_path, "srv", *_pki.issue(ca_key, ca, "bastion", "127.0.0.1"))
    paths["cp1"] = _pki.write_pair(tmp_path, "cp1", *_pki.issue(ca_key, ca, "CP1"))
    rogue_key, rogue = _pki.make_ca("rogue")
    paths["rogue"] = _pki.write_pair(tmp_path, "rogue", *_pki.issue(rogue_key, rogue, "CP1"))
    return paths


def client_ctx(pki, pair=None):
    ctx = ssl.create_default_context(cafile=pki["ca"])
    ctx.check_hostname = False
    if pair:
        ctx.load_cert_chain(*pair)
    return ctx


def mtls_cfg(pki):
    cert, key = pki["srv"]
    return make_cfg(tls_cert=cert, tls_key=key, tls_ca=pki["ca"])


def test_mtls_accepts_valid_client_and_uses_cn(pki):
    async def scenario():
        async def echo(ws):
            async for m in ws:
                await ws.send("echo:" + m)

        up = await serve_upstream(echo)
        proxy = OCPPProxy(mtls_cfg(pki), bind="127.0.0.1")
        await proxy.start()
        try:
            async with websockets.connect(
                f"wss://127.0.0.1:{P16}/ocpp/CP1", subprotocols=["ocpp1.6"],
                ssl=client_ctx(pki, pki["cp1"]),
            ) as cp:
                await cp.send(FRAME)
                assert await cp.recv() == "echo:" + FRAME
                assert proxy.active_chargers() == ["CP1"]
        finally:
            await proxy.stop()
            up.close()
            await up.wait_closed()

    run(scenario())


def test_mtls_refuses_without_client_cert(pki):
    async def scenario():
        proxy = OCPPProxy(mtls_cfg(pki), bind="127.0.0.1")
        await proxy.start()
        try:
            with pytest.raises(Exception):
                async with websockets.connect(
                    f"wss://127.0.0.1:{P16}/ocpp/CP1", subprotocols=["ocpp1.6"],
                    ssl=client_ctx(pki),
                ) as cp:
                    await asyncio.wait_for(cp.recv(), 5)   # TLS1.3 reports the alert here
            assert proxy.active_chargers() == []
        finally:
            await proxy.stop()

    run(scenario())


def test_mtls_refuses_client_cert_from_other_ca(pki):
    async def scenario():
        proxy = OCPPProxy(mtls_cfg(pki), bind="127.0.0.1")
        await proxy.start()
        try:
            with pytest.raises(Exception):
                async with websockets.connect(
                    f"wss://127.0.0.1:{P16}/ocpp/CP1", subprotocols=["ocpp1.6"],
                    ssl=client_ctx(pki, pki["rogue"]),
                ) as cp:
                    await asyncio.wait_for(cp.recv(), 5)
        finally:
            await proxy.stop()

    run(scenario())


def test_mtls_rejects_cn_path_mismatch(pki):
    async def scenario():
        proxy = OCPPProxy(mtls_cfg(pki), bind="127.0.0.1")
        await proxy.start()
        try:
            async with websockets.connect(
                f"wss://127.0.0.1:{P16}/ocpp/OTHER", subprotocols=["ocpp1.6"],
                ssl=client_ctx(pki, pki["cp1"]),
            ) as cp:
                with pytest.raises(websockets.exceptions.ConnectionClosed) as ei:
                    await asyncio.wait_for(cp.recv(), 5)
                code = ei.value.rcvd.code
                assert code == 1008
            assert proxy.active_chargers() == []
        finally:
            await proxy.stop()

    run(scenario())


def test_upstream_tls_requires_ca_or_explicit_optout(caplog):
    from gateway.proxy import _build_ssl_context
    with pytest.raises(ValueError, match="upstream_verify"):
        _build_ssl_context("", "", "")
    with caplog.at_level("WARNING"):
        ctx = _build_ssl_context("", "", "", verify=False)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert "VERIFICATION DISABLED" in caplog.text
