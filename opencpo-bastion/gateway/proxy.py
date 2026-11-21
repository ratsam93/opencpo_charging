"""
OpenCPO Bastion — OCPP WebSocket Proxy

Listens on the local network for OCPP charger connections and forwards
them to the upstream OpenCPO Core via a mTLS-authenticated WebSocket
over the Tailscale tunnel.

Ports:
  0.0.0.0:9100  — OCPP 1.6
  0.0.0.0:9201  — OCPP 2.0.1

Features:
  - Transparent bidirectional WebSocket proxy
  - mTLS client cert from keyvault
  - Upstream reconnection with exponential backoff (cap: 60s); the charger
    connection is kept and a small bounded number of frames is buffered
  - All frames logged to shared ring buffer (tap.py reads it)
  - Charger-facing listener: optional TLS / mTLS (tls_cert, tls_key, tls_ca).
    With mTLS the charger ID comes from the client certificate CN and must
    match the URL path. Without TLS the listener refuses non-loopback binds
    unless `allow_insecure: true` (path-only identity, loud warning).
  - Upstream TLS is always verified unless `upstream_verify: false`
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import ssl
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import websockets
import websockets.exceptions

from gateway.config import GatewayConfig

logger = logging.getLogger(__name__)

# Shared ring buffer consumed by tap.py
# deque is thread-safe for single-producer append
_message_buffer: deque = deque(maxlen=10_000)


@dataclass
class ProxiedMessage:
    charger_id: str
    direction: str      # "up" (charger→core) | "down" (core→charger)
    action: str         # extracted OCPP action if parseable
    payload: str
    timestamp: float = field(default_factory=time.time)


def get_message_buffer() -> deque:
    return _message_buffer


def _extract_action(payload: str) -> str:
    """Best-effort extract of OCPP action name from JSON frame."""
    try:
        import json
        msg = json.loads(payload)
        if isinstance(msg, list) and len(msg) >= 3:
            return str(msg[2]) if len(msg) == 4 else ""
    except Exception:
        pass
    return ""


def _extract_charger_id(path: str) -> str:
    """Extract charger ID from WebSocket path: /ocpp/CHARGER-001 → CHARGER-001"""
    parts = [p for p in path.strip("/").split("/") if p]
    return parts[-1] if parts else "unknown"


def _build_ssl_context(
    cert_path: str,
    key_path: str,
    ca_path: str,
    verify: bool = True,
    vault=None,
) -> ssl.SSLContext:
    """
    Client-side (upstream) TLS context.

    Never silently disables verification: without a CA file this raises unless
    the operator explicitly set ``upstream_verify: false``.
    """
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    if ca_path:
        ctx.load_verify_locations(ca_path)
    elif verify:
        raise ValueError(
            "No CA certificate available to verify the upstream Core; provide a CA "
            "or set `upstream_verify: false` explicitly (insecure)"
        )
    if not verify:
        logger.warning(
            "UPSTREAM TLS VERIFICATION DISABLED (upstream_verify: false) — "
            "the Core connection can be intercepted"
        )
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if cert_path and (key_path or vault is not None):
        _load_chain(ctx, cert_path, key_path, vault)
    return ctx


def _load_chain(ctx: ssl.SSLContext, cert_path: str, key_path: str, vault=None) -> None:
    """Load cert+key; if a vault is given, decrypt the key to tmpfs and delete it right after."""
    if vault is None:
        ctx.load_cert_chain(cert_path, key_path)
        return
    path, cleanup = vault.decrypt_key_to_tmpfs()
    try:
        ctx.load_cert_chain(cert_path, path)
    finally:
        cleanup()


def _build_server_ssl_context(cert: str, key: str, ca: str = "") -> ssl.SSLContext:
    """Charger-facing TLS context; client certs are mandatory when a CA is given."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    if ca:
        ctx.load_verify_locations(ca)
        ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _request_path(websocket, path: Optional[str] = None) -> str:
    """Request path on websockets>=13 (ws.request.path) or legacy (path arg / ws.path)."""
    request = getattr(websocket, "request", None)
    if request is not None and getattr(request, "path", None) is not None:
        return request.path
    if path is not None:
        return path
    return getattr(websocket, "path", "") or ""


def _peer_cn(websocket) -> str:
    """Common name of the verified client certificate, or "" if none."""
    try:
        ssl_obj = websocket.transport.get_extra_info("ssl_object")
        cert = ssl_obj.getpeercert() if ssl_obj else None
    except Exception:
        return ""
    for rdn in (cert or {}).get("subject", ()):
        for key, value in rdn:
            if key == "commonName":
                return value
    return ""


class OCPPProxyConnection:
    """
    Handles a single charger <-> core proxy session.
    Lives as long as the charger WebSocket is open; the upstream leg is
    re-established with backoff while the charger stays connected.
    """

    def __init__(
        self,
        charger_ws,
        charger_id: str,
        core_url: str,
        ssl_ctx: Optional[ssl.SSLContext],
        ocpp_version: str,
        max_attempts: int = 10,
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
        buffer_size: int = 50,
    ):
        self.charger_ws = charger_ws
        self.charger_id = charger_id
        self.core_url = core_url
        self.ssl_ctx = ssl_ctx
        self.ocpp_version = ocpp_version
        self.max_attempts = max_attempts
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        # Frames from the charger waiting for the upstream (oldest dropped when full)
        self._outbox: deque = deque(maxlen=buffer_size)
        self._wakeup = asyncio.Event()
        self._charger_closed = asyncio.Event()

    def _log(self, direction: str, message) -> None:
        payload = message if isinstance(message, str) else message.decode(errors="replace")
        _message_buffer.append(ProxiedMessage(
            charger_id=self.charger_id,
            direction=direction,
            action=_extract_action(payload),
            payload=payload,
        ))

    async def _charger_reader(self) -> None:
        """Read the charger socket for its whole lifetime, buffering for the upstream."""
        try:
            async for message in self.charger_ws:
                self._log("up", message)
                self._outbox.append(message)
                self._wakeup.set()
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.warning("[%s] Charger read error: %s", self.charger_id, e)
        finally:
            self._charger_closed.set()
            self._wakeup.set()

    async def _send_up(self, core_ws) -> None:
        """Flush buffered charger frames to the upstream."""
        while True:
            while self._outbox:
                msg = self._outbox.popleft()
                try:
                    await core_ws.send(msg)
                except BaseException:
                    self._outbox.appendleft(msg)
                    raise
            if self._charger_closed.is_set():
                return
            self._wakeup.clear()
            if self._outbox or self._charger_closed.is_set():
                continue
            await self._wakeup.wait()

    async def _recv_down(self, core_ws) -> None:
        """Relay upstream frames to the charger. Returns when upstream ends."""
        async for message in core_ws:
            self._log("down", message)
            try:
                await self.charger_ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                self._charger_closed.set()
                self._wakeup.set()
                return

    async def _session(self) -> None:
        upstream_url = f"{self.core_url}/{self.charger_id}"
        logger.info("[%s] Connecting to core: %s", self.charger_id, upstream_url)
        async with websockets.connect(
            upstream_url,
            ssl=self.ssl_ctx,
            subprotocols=[f"ocpp{self.ocpp_version}"],
            ping_interval=30,
            ping_timeout=10,
        ) as core_ws:
            logger.info("[%s] Upstream connected", self.charger_id)
            self._attempts = 0
            self._backoff = self.initial_backoff
            tasks = [
                asyncio.create_task(self._send_up(core_ws)),
                asyncio.create_task(self._recv_down(core_ws)),
            ]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    if not t.cancelled() and t.exception():
                        raise t.exception()
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        # leaving the `async with` closes the upstream (no zombie sessions)

    async def run(self) -> None:
        self._attempts = 0
        self._backoff = self.initial_backoff
        reader = asyncio.create_task(self._charger_reader())
        try:
            while not self._charger_closed.is_set():
                try:
                    await self._session()
                    logger.info("[%s] Upstream connection closed", self.charger_id)
                except asyncio.CancelledError:
                    raise
                except websockets.exceptions.ConnectionClosed:
                    logger.info("[%s] Upstream connection closed", self.charger_id)
                except Exception as e:
                    logger.warning("[%s] Upstream error: %s", self.charger_id, e)

                if self._charger_closed.is_set():
                    break
                self._attempts += 1
                if self._attempts > self.max_attempts:
                    logger.error(
                        "[%s] Upstream unreachable after %d attempts — closing charger",
                        self.charger_id, self.max_attempts,
                    )
                    try:
                        await self.charger_ws.close(code=1011, reason="upstream unavailable")
                    except Exception:
                        pass
                    break
                logger.info("[%s] Reconnecting upstream in %.1fs (%d/%d)",
                            self.charger_id, self._backoff, self._attempts, self.max_attempts)
                try:
                    await asyncio.wait_for(self._charger_closed.wait(), self._backoff)
                except asyncio.TimeoutError:
                    pass
                self._backoff = min(self._backoff * 2, self.max_backoff)
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)


class OCPPProxy:
    """Manages listener servers for OCPP 1.6 and 2.0.1."""

    def __init__(
        self,
        config: GatewayConfig,
        cert_path: str = "",
        key_path: str = "",
        ca_path: str = "",
        vault=None,
        bind: str = "0.0.0.0",
    ):
        self.config = config
        self.bind = bind
        self.vault = vault
        verify = getattr(config, "upstream_verify", True)
        self.ssl_ctx = (
            _build_ssl_context(cert_path, key_path, ca_path, verify=verify, vault=vault)
            if (cert_path or not verify) else None
        )
        self._active: dict[str, asyncio.Task] = {}
        self._servers: list = []
        self.conn_kwargs: dict = {}  # OCPPProxyConnection overrides (backoff, buffer, ...)

    @property
    def mtls(self) -> bool:
        return bool(getattr(self.config, "tls_cert", "") and getattr(self.config, "tls_ca", ""))

    def _check_listener_security(self) -> None:
        """Refuse an unauthenticated listener on a non-loopback address unless opted in."""
        if self.mtls:
            return
        allow = getattr(self.config, "allow_insecure", False)
        if not _is_loopback(self.bind) and not allow:
            raise RuntimeError(
                f"Refusing to listen on {self.bind} without mTLS: configure tls_cert, "
                "tls_key and tls_ca, or set `allow_insecure: true` explicitly"
            )
        if allow:
            logger.warning(
                "INSECURE LISTENER: charger connections on %s are NOT mutually authenticated; "
                "charger identity is taken from the URL path and can be spoofed "
                "(allow_insecure: true)", self.bind,
            )

    async def _handle_charger(self, websocket, path: Optional[str] = None, ocpp_version: str = "1.6") -> None:
        url_id = _extract_charger_id(_request_path(websocket, path))
        if self.mtls:
            cn = _peer_cn(websocket)
            if not cn or cn != url_id:
                logger.warning("Rejecting charger: certificate CN %r does not match path ID %r",
                               cn, url_id)
                await websocket.close(code=1008, reason="identity mismatch")
                return
            charger_id = cn
        else:
            charger_id = url_id
        logger.info("Charger connected: %s (OCPP %s)", charger_id, ocpp_version)

        core_base = self.config.core_api_base
        core_url = f"{core_base.replace('http', 'ws', 1)}/ocpp/{ocpp_version}"
        conn = OCPPProxyConnection(
            charger_ws=websocket,
            charger_id=charger_id,
            core_url=core_url,
            ssl_ctx=self.ssl_ctx if core_url.startswith("wss") else None,
            ocpp_version=ocpp_version,
            **self.conn_kwargs,
        )

        task = asyncio.current_task()
        self._active[charger_id] = task
        try:
            await conn.run()
        finally:
            if self._active.get(charger_id) is task:
                self._active.pop(charger_id, None)
            logger.info("Charger disconnected: %s", charger_id)

    async def start(self) -> None:
        """Bind both listeners (returns once listening)."""
        self._check_listener_security()
        server_ssl = None
        cfg = self.config
        if getattr(cfg, "tls_cert", ""):
            server_ssl = _build_server_ssl_context(
                cfg.tls_cert, cfg.tls_key, getattr(cfg, "tls_ca", ""))
        elif getattr(cfg, "tls_ca", ""):
            raise RuntimeError("tls_ca set without tls_cert/tls_key")
        p16 = cfg.proxy_ports.ocpp16
        p201 = cfg.proxy_ports.ocpp201

        async def h16(ws, path=None):
            await self._handle_charger(ws, path, "1.6")

        async def h201(ws, path=None):
            await self._handle_charger(ws, path, "2.0.1")

        self._servers = [
            await websockets.serve(h16, self.bind, p16, ssl=server_ssl,
                                   subprotocols=["ocpp1.6"]),
            await websockets.serve(h201, self.bind, p201, ssl=server_ssl,
                                   subprotocols=["ocpp2.0.1", "ocpp2.0"]),
        ]
        logger.info("OCPP proxy listening: %s:%d (1.6), %s:%d (2.0.1) [%s]",
                    self.bind, p16, self.bind, p201,
                    "mTLS" if self.mtls else "TLS" if server_ssl else "plaintext")

    async def stop(self) -> None:
        for srv in self._servers:
            srv.close()
        for srv in self._servers:
            await srv.wait_closed()
        self._servers = []

    async def run(self) -> None:
        await self.start()
        await asyncio.gather(*(srv.wait_closed() for srv in self._servers))

    def active_chargers(self) -> list[str]:
        return list(self._active.keys())
