"""
Authentication routes for OpenCPO Admin.

Handles login/logout via OCPP Core's JWT-based admin auth endpoint.
Session is stored in a signed cookie (JWT).
"""
import logging
import os
import time

import httpx
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from shared import templates, CORE_API, verify_session

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Login rate limiting (in-memory, per client IP) ───────────────────────────
_MAX_FAILURES = 10
_WINDOW_SECONDS = 300
_failures: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _recent_failures(ip: str) -> list[float]:
    cutoff = time.monotonic() - _WINDOW_SECONDS
    recent = [t for t in _failures.get(ip, []) if t > cutoff]
    if recent:
        _failures[ip] = recent
    else:
        _failures.pop(ip, None)
    return recent


def _is_rate_limited(ip: str) -> bool:
    return len(_recent_failures(ip)) >= _MAX_FAILURES


def _record_failure(ip: str) -> None:
    _recent_failures(ip)
    _failures.setdefault(ip, []).append(time.monotonic())


# ── Session cookie ───────────────────────────────────────────────────────────
def _cookie_secure() -> bool:
    env = os.getenv("COOKIE_SECURE")
    if env is not None and env.strip() != "":
        return env.strip().lower() in ("1", "true", "yes", "on")
    return os.getenv("PUBLIC_URL", "").lower().startswith("https")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render login page. Redirect to / if already authenticated."""
    user = await verify_session(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(request, "login.html", context={"error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    """Validate credentials against OCPP Core and issue a JWT session cookie."""
    ip = _client_ip(request)
    if _is_rate_limited(ip):
        logger.warning("Login rate limit hit for %s", ip)
        return templates.TemplateResponse(
            request, "login.html",
            context={"error": "Too many failed login attempts. Please try again in a few minutes."},
            status_code=429, headers={"Retry-After": str(_WINDOW_SECONDS)},
        )
    error = None
    try:
        async with httpx.AsyncClient(base_url=CORE_API, timeout=10) as client:
            r = await client.post(
                "/api/v1/admin/auth/login",
                json={"email": email, "password": password},
            )
            data = r.json()

        if r.status_code == 200:
            token = data.get("token", "")
            user = data.get("user", {})
            response = RedirectResponse("/", status_code=302)
            response.set_cookie(
                key="opencpo_session",
                value=token,
                max_age=86400,          # 24 hours
                path="/",               # available on every page
                httponly=True,
                samesite="lax",
                secure=_cookie_secure(),
            )
            return response

        _record_failure(ip)
        error = data.get("detail", "Invalid email or password.")

    except httpx.RequestError:
        error = "Could not connect to authentication service. Please try again."
    except Exception:
        logger.exception("Unexpected error during login")
        error = "An unexpected error occurred. Please try again."

    return templates.TemplateResponse(
        request, "login.html", context={"error": error}
    )


@router.post("/logout")
async def logout():
    """Clear session cookie and redirect to login."""
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("opencpo_session")
    return response
