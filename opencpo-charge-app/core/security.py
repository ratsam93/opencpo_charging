"""Session ownership, error sanitising and security headers."""
import logging
import time

import jwt
from fastapi import HTTPException
from fastapi.responses import JSONResponse

import config
from core.api import api_get

logger = logging.getLogger(__name__)

SESSION_COOKIE = "session_access"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
MAX_SESSIONS_IN_COOKIE = 20
_TOKEN_TYPE = "session-access"


# ── Session ownership ────────────────────────────────────────────────────

def _owned_session_ids(request) -> list[str]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return []
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return []
    if payload.get("typ") != _TOKEN_TYPE:
        return []
    sids = payload.get("sids")
    return [str(s) for s in sids] if isinstance(sids, list) else []


def grant_session(request, response, session_id: str) -> None:
    """Remember (in a signed cookie) that this browser created session_id."""
    sids = [s for s in _owned_session_ids(request) if s != str(session_id)]
    sids.append(str(session_id))
    sids = sids[-MAX_SESSIONS_IN_COOKIE:]
    token = jwt.encode(
        {"typ": _TOKEN_TYPE, "sids": sids, "exp": int(time.time()) + SESSION_COOKIE_MAX_AGE},
        config.JWT_SECRET, algorithm="HS256",
    )
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_COOKIE_MAX_AGE,
        httponly=True, secure=config.COOKIE_SECURE, samesite="lax", path="/",
    )


def browser_owns(request, session_id: str) -> bool:
    return str(session_id) in _owned_session_ids(request)


_OWNER_KEYS = ("account_id", "driver_id", "driver_account_id")


async def authorize_session(request, session_id: str):
    """Return (allowed, session_data_or_None).

    Allowed when this browser created the session (signed cookie) or the
    logged-in account owns it according to Core. Core's field name for the
    owner is not documented, so _OWNER_KEYS lists the candidates; if none is
    present the account route denies access (fail closed).
    """
    if not config.SESSION_OWNERSHIP_CHECK:
        return True, None
    if browser_owns(request, session_id):
        return True, None
    account = getattr(request.state, "account", None)
    if account and account.get("id"):
        try:
            data = await api_get(f"/api/v1/public/sessions/{session_id}")
        except Exception as e:
            logger.warning("Ownership lookup failed for %s: %s", session_id, e)
            return False, None
        for key in _OWNER_KEYS:
            owner = data.get(key) if isinstance(data, dict) else None
            if owner is not None and str(owner) == str(account["id"]):
                return True, data
    return False, None


def forbidden() -> JSONResponse:
    return JSONResponse({"error": "You do not have access to this session."}, status_code=403)


# ── Error handling ───────────────────────────────────────────────────────

def safe_error(exc: Exception, fallback: str = "Service temporarily unavailable.") -> JSONResponse:
    """Log the real error; never return internals (URLs, stack text) to the browser.

    4xx messages from Core's API (e.g. "Connector busy") are user-facing and
    kept; everything else becomes a generic message.
    """
    if isinstance(exc, HTTPException) and 400 <= exc.status_code < 500:
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)
    logger.error("Upstream error: %r", exc)
    status = exc.status_code if isinstance(exc, HTTPException) and exc.status_code >= 500 else 502
    return JSONResponse({"error": fallback}, status_code=status)


# ── Security headers ─────────────────────────────────────────────────────

_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",      # templates use inline scripts
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    "img-src 'self' data: blob: https:",      # map tiles / skin images
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
])

SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # camera is needed for QR scanning; geolocation for the charger map
    "Permissions-Policy": "camera=(self), geolocation=(self), microphone=()",
}


async def security_headers(request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if config.COOKIE_SECURE:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response
