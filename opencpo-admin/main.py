"""
OpenCPO Admin — Network management dashboard.

FastAPI + Jinja2 + HTMX. No React, no npm, no build step.
Consumes OCPP Core via REST API only — no direct DB or Redis access.

Route modules live in routes/. Shared helpers in shared.py.
"""
import os
import logging

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import urlparse
from starlette.middleware.base import BaseHTTPMiddleware

from shared import APP_TITLE, verify_session, get_setup_status

# Route modules
from routes.dashboard import router as dashboard_router
from routes.chargers import router as chargers_router
from routes.sessions import router as sessions_router
from routes.tariffs import router as tariffs_router
from routes.tokens import router as tokens_router
from routes.groups import router as groups_router
from routes.drivers import router as drivers_router
from routes.receipts import router as receipts_router
from routes.pki import router as pki_router
from routes.security import router as security_router
from routes.onboarding import router as onboarding_router
from routes.ocpp import router as ocpp_router
from routes.settings import router as settings_router
from routes.ocpi_mgmt import router as ocpi_mgmt_router
from routes.docs import router as docs_router
from routes.network import router as network_router
from routes.skins import router as skins_router
from routes.auth import router as auth_router
from routes.setup import router as setup_router
from routes.updates import router as updates_router
from routes.backup import router as backup_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths that don't require authentication
_PUBLIC_PREFIXES = ("/login", "/logout", "/setup", "/static", "/favicon.ico", "/health")


def _is_public(path: str) -> bool:
    """Exact match or path-segment boundary match (so /setupXYZ is NOT public)."""
    return any(path == p or path.startswith(p + "/") for p in _PUBLIC_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticate requests. Redirects unauthenticated users to setup wizard
    if the platform hasn't been configured yet, or to login otherwise."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Allow public paths through unconditionally
        if _is_public(path):
            return await call_next(request)

        user = await verify_session(request)
        if user is None:
            logger.warning("AuthMiddleware: redirecting to /login from %s", path)
            return RedirectResponse("/login", status_code=302)

        request.state.user = user
        return await call_next(request)


# Setup completion never reverts, so once core has said "complete" we stop asking.
# (Before this, every page made an extra core call; when core rate-limited the
# admin container's single IP the whole UI failed closed with 503.)
_SETUP_COMPLETE = False


class SetupCheckMiddleware(BaseHTTPMiddleware):
    """Check if platform setup is complete. Redirect to /setup if not.
    Runs BEFORE AuthMiddleware so that first-time visitors get the
    setup wizard instead of the login page."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Skip for static files, setup routes, login
        if _is_public(path):
            return await call_next(request)

        global _SETUP_COMPLETE
        if _SETUP_COMPLETE:
            return await call_next(request)

        # Check setup status — redirect ANYONE (authed or not) to /setup
        # if the platform hasn't been configured yet.
        try:
            status = await get_setup_status(strict=True)
        except Exception:
            # Fail closed: if core is unreachable we cannot tell whether setup
            # is complete, so do not serve the admin UI.
            logger.warning("SetupCheckMiddleware: core unreachable for %s", path)
            return HTMLResponse(
                '<!doctype html><title>Service unavailable</title>'
                '<body style="font-family:sans-serif;background:#0a1221;color:#c0cdd8;padding:2rem">'
                '<h1>503 - Service unavailable</h1>'
                '<p>The OpenCPO core API is not reachable. Please try again shortly.</p></body>',
                status_code=503, headers={"Retry-After": "10"},
            )
        if not status.get("complete", False):
            return RedirectResponse("/setup", status_code=302)

        _SETUP_COMPLETE = True
        return await call_next(request)


_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin state-changing requests.

    If an Origin header is present (all browsers send it on cross-origin POSTs)
    its host must match the request Host. Without Origin, fall back to Referer.
    Requests with neither (non-browser clients) are allowed; they cannot ride
    on a victim's cookies. Same-origin htmx requests carry a matching Origin.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in _UNSAFE_METHODS:
            source = request.headers.get("origin")
            if source is None:
                source = request.headers.get("referer")
            if source is not None:
                allowed = {request.headers.get("host", "")}
                fwd = request.headers.get("x-forwarded-host")
                if fwd:
                    allowed.add(fwd.split(",")[0].strip())
                host = urlparse(source).netloc
                if not host or host not in allowed:
                    logger.warning("CSRF: blocked %s %s from %r", request.method, request.url.path, source)
                    return HTMLResponse("Cross-origin request blocked", status_code=403)
        return await call_next(request)


# Inline scripts/styles and the Tailwind play script are used throughout the
# templates, so 'unsafe-inline' is required. Browser-side fetch/EventSource go
# to the (configurable) core API URL, so connect-src is left open.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https: http:; "
    "font-src 'self' data:; "
    "connect-src *; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Content-Security-Policy", _CSP)
        return response


app = FastAPI(title=APP_TITLE, docs_url=None, redoc_url=None)
app.add_middleware(AuthMiddleware)
app.add_middleware(SetupCheckMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Register all route modules
app.include_router(dashboard_router)
app.include_router(chargers_router)
app.include_router(sessions_router)
app.include_router(tariffs_router)
app.include_router(tokens_router)
app.include_router(groups_router)
app.include_router(drivers_router)
app.include_router(receipts_router)
app.include_router(pki_router)
app.include_router(security_router)
app.include_router(onboarding_router)
app.include_router(ocpp_router)
app.include_router(settings_router)
app.include_router(ocpi_mgmt_router)
app.include_router(docs_router)
app.include_router(network_router)
app.include_router(skins_router)
app.include_router(auth_router)
app.include_router(setup_router)
app.include_router(updates_router)
app.include_router(backup_router)


# ── Health Endpoint ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Liveness check — verifies the service is running and core API is reachable."""
    from shared import CORE_API
    import httpx
    core_ok = False
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{CORE_API}/health")
            core_ok = r.status_code == 200
    except Exception:
        pass
    return {
        "status": "ok" if core_ok else "starting",
        "service": "cpo-admin",
        "core_api": "reachable" if core_ok else "waiting",
    }


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("main:app", host=host, port=port, reload=True)
