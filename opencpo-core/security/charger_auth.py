"""Charger authentication for the OCPP WebSocket servers (ports 9100 / 9201).

Before this module any client could connect as any charge point id: unknown ids
were auto-registered, no credentials were checked and an empty id created a
charge point named "". Now a connection is accepted only when ONE of these holds:

1. **Per-charger password** (OCPP security profile 1/2): HTTP Basic auth with the
   charge point id as user name and a per-charger secret as password. Secrets are
   stored as bcrypt hashes and managed through /api/v1/charger-credentials.
2. **Client certificate** (security profile 3): when TLS is on and the charger
   presents a certificate, its common name must equal the charge point id.
3. **Trusted network or host**: the peer address is inside OCPP_TRUSTED_CIDRS, or
   resolves from one of OCPP_TRUSTED_HOSTS (for example a Bastion on the private
   mesh, or the charger-farm simulator container). This is explicit opt-in.

OCPP_AUTH_MODE=off restores the old open behaviour (development only).

Repeated failures from one address are throttled (HTTP 429).
"""
import asyncio
import base64
import binascii
import ipaddress
import logging
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import urlsplit

import bcrypt

logger = logging.getLogger(__name__)

CP_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]{1,64}$")
MIN_PASSWORD_LENGTH = 16
_THROTTLE_FAILURES = 10
_THROTTLE_WINDOW_S = 60
_HOST_CACHE_S = 30


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    status: int = HTTPStatus.OK
    reason: str = ""
    method: str = ""


def cp_id_from_path(path: str) -> str:
    """Last non-empty URL path segment: /ocpp/CP001?x=1 -> CP001 ('' when there is none)."""
    segments = [s for s in urlsplit(path or "").path.split("/") if s]
    return segments[-1] if segments else ""


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _parse_ip(value: str):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def parse_basic(header: str | None) -> tuple[str, str] | None:
    """'Basic base64(user:password)' -> (user, password); the password may contain ':'."""
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    user, sep, password = decoded.partition(":")
    return (user, password) if sep else None


class ChargerAuthenticator:
    def __init__(self, db, mode: str = "required", trusted_cidrs=(), trusted_hosts=(), resolver=None):
        self._db = db
        self.mode = mode
        self.trusted_networks = []
        for c in trusted_cidrs:
            try:
                self.trusted_networks.append(ipaddress.ip_network(c, strict=False))
            except ValueError:
                logger.error("OCPP_TRUSTED_CIDRS: ignoring invalid network %r", c)
        self.trusted_hosts = list(trusted_hosts)
        self._resolver = resolver or self._resolve
        self._host_ips: set = set()
        self._host_ips_at = 0.0
        self._failures: dict[str, deque] = defaultdict(deque)
        self._dummy_hash = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt())

    @classmethod
    def from_env(cls, db):
        mode = os.getenv("OCPP_AUTH_MODE", "required").strip().lower()
        if mode not in ("required", "off"):
            logger.error("OCPP_AUTH_MODE=%r is not valid (required|off); using 'required'", mode)
            mode = "required"
        auth = cls(db, mode,
                   _split_csv(os.getenv("OCPP_TRUSTED_CIDRS", "")),
                   _split_csv(os.getenv("OCPP_TRUSTED_HOSTS", "")))
        if mode == "off":
            logger.warning("OCPP_AUTH_MODE=off: ANY client can connect as ANY charge point (development only)")
        else:
            logger.info("OCPP charger authentication: required (trusted networks=%s hosts=%s)",
                        [str(n) for n in auth.trusted_networks], auth.trusted_hosts)
        return auth

    # ── trust ────────────────────────────────────────────────────────────

    @staticmethod
    async def _resolve(host: str) -> set:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, None)
        except OSError:
            return set()
        return {ip for ip in (_parse_ip(i[4][0]) for i in infos) if ip}

    async def _is_trusted(self, ip) -> bool:
        if any(ip in net for net in self.trusted_networks):
            return True
        if not self.trusted_hosts:
            return False
        if time.monotonic() - self._host_ips_at > _HOST_CACHE_S:
            ips: set = set()
            for host in self.trusted_hosts:
                ips |= await self._resolver(host)
            self._host_ips, self._host_ips_at = ips, time.monotonic()
        return ip in self._host_ips

    # ── throttle ─────────────────────────────────────────────────────────

    def _throttled(self, peer: str) -> bool:
        q = self._failures[peer]
        cutoff = time.monotonic() - _THROTTLE_WINDOW_S
        while q and q[0] < cutoff:
            q.popleft()
        return len(q) >= _THROTTLE_FAILURES

    def _fail(self, peer: str, status: int, reason: str) -> AuthDecision:
        self._failures[peer].append(time.monotonic())
        logger.warning("OCPP connection refused from %s: %s", peer or "?", reason)
        return AuthDecision(False, status, reason)

    # ── the decision ─────────────────────────────────────────────────────

    async def authenticate(self, cp_id: str, authorization: str | None, peer: str,
                           cert_cn: str | None = None) -> AuthDecision:
        if self.mode == "off":
            return AuthDecision(True, method="off")
        if not CP_ID_RE.match(cp_id or ""):
            return AuthDecision(False, HTTPStatus.BAD_REQUEST, "Invalid charge point id")
        ip = _parse_ip(peer or "")
        if ip is not None and await self._is_trusted(ip):
            return AuthDecision(True, method="trusted-network")
        if self._throttled(peer):
            return AuthDecision(False, HTTPStatus.TOO_MANY_REQUESTS, "Too many failed attempts, try again later")
        if cert_cn is not None:
            if cert_cn == cp_id:
                return AuthDecision(True, method="client-certificate")
            return self._fail(peer, HTTPStatus.FORBIDDEN,
                              f"Client certificate {cert_cn!r} does not match charge point id")
        creds = parse_basic(authorization)
        if creds is None:
            return self._fail(peer, HTTPStatus.UNAUTHORIZED, "Authorization required")
        user, password = creds
        stored = None
        if user == cp_id:
            async with self._db.read() as conn:
                row = await conn.fetchrow(
                    "SELECT password_hash FROM ocpp.charger_credentials "
                    "WHERE charge_point = $1 AND revoked_at IS NULL", cp_id)
            stored = row["password_hash"] if row else None
        # always run bcrypt so unknown ids and wrong passwords take the same time
        ok = await asyncio.to_thread(
            bcrypt.checkpw, password.encode(), (stored or self._dummy_hash.decode()).encode())
        if user == cp_id and stored and ok:
            return AuthDecision(True, method="password")
        return self._fail(peer, HTTPStatus.UNAUTHORIZED, "Invalid credentials")

    # ── credential management (used by the REST API) ─────────────────────

    async def set_password(self, cp_id: str, password: str) -> None:
        hashed = await asyncio.to_thread(bcrypt.hashpw, password.encode(), bcrypt.gensalt())
        async with self._db.write() as conn:
            await conn.execute("""
                INSERT INTO ocpp.charger_credentials (charge_point, password_hash)
                VALUES ($1, $2)
                ON CONFLICT (charge_point) DO UPDATE
                   SET password_hash = $2, updated_at = NOW(), revoked_at = NULL
            """, cp_id, hashed.decode())

    async def revoke(self, cp_id: str) -> bool:
        async with self._db.write() as conn:
            row = await conn.fetchrow("""
                UPDATE ocpp.charger_credentials SET revoked_at = NOW(), updated_at = NOW()
                 WHERE charge_point = $1 AND revoked_at IS NULL RETURNING charge_point
            """, cp_id)
        return row is not None

    async def list_credentials(self) -> list[dict]:
        async with self._db.read() as conn:
            rows = await conn.fetch(
                "SELECT charge_point, created_at, updated_at, revoked_at "
                "FROM ocpp.charger_credentials ORDER BY charge_point")
        return [dict(r) for r in rows]


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS ocpp.charger_credentials (
    charge_point  TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at    TIMESTAMPTZ
)
"""


async def ensure_schema(db) -> None:
    """Create the credentials table on databases that were set up before it existed."""
    async with db.write() as conn:
        await conn.execute(CREATE_TABLE_SQL)


# Set by main.py at startup
authenticator: ChargerAuthenticator | None = None


def _client_cert_cn(connection) -> str | None:
    """Common name of the verified TLS client certificate, if the charger presented one."""
    try:
        ssl_object = connection.transport.get_extra_info("ssl_object")
        cert = ssl_object.getpeercert() if ssl_object else None
    except Exception:
        return None
    if not cert:
        return None
    for rdn in cert.get("subject", ()):
        for key, value in rdn:
            if key == "commonName":
                return value
    return None


async def authenticate_upgrade(connection, request):
    """`process_request` hook for websockets.serve(): refuse unauthenticated chargers
    with an HTTP error before the WebSocket handshake completes (OCPP security profiles)."""
    peer = connection.remote_address[0] if connection.remote_address else ""
    decision = await get_authenticator().authenticate(
        cp_id_from_path(request.path), request.headers.get("Authorization"), peer,
        _client_cert_cn(connection))
    if decision.allowed:
        return None
    response = connection.respond(HTTPStatus(int(decision.status)), decision.reason + "\n")
    if int(decision.status) == HTTPStatus.UNAUTHORIZED:
        response.headers["WWW-Authenticate"] = 'Basic realm="OCPP", charset="UTF-8"'
    return response


def get_authenticator() -> ChargerAuthenticator:
    if authenticator is None:
        raise RuntimeError("charger authenticator not initialised")
    return authenticator
