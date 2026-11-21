"""Thin HTTP proxy to the OCPP Core API."""
import logging
import os

import httpx
from fastapi import HTTPException

import config

logger = logging.getLogger(__name__)

CORE_API_KEY = os.getenv("MANAGEMENT_API_KEY", "")


PUBLIC_PREFIX = "/api/v1/public/"
# Reading, stopping or cancelling a session needs the management key on Core. This app
# only makes those calls AFTER core/security.py has checked that the caller owns the
# session. Creating a session and the other public routes stay anonymous: the key is
# never attached to them.
SESSION_SCOPED_PREFIX = "/api/v1/public/sessions/"
_ANONYMOUS_SESSION_PATHS = ("/api/v1/public/sessions/pending",)


def _auth_headers(path: str = "") -> dict:
    """X-API-Key for server-to-server calls that Core protects with the management key."""
    if path.startswith(PUBLIC_PREFIX):
        scoped = path.startswith(SESSION_SCOPED_PREFIX) and not path.startswith(_ANONYMOUS_SESSION_PATHS)
        if not scoped:
            return {}
    return {"X-API-Key": CORE_API_KEY} if CORE_API_KEY else {}


async def api_get(path: str) -> dict:
    """GET request to Core API. Raises HTTPException on failure."""
    async with httpx.AsyncClient(base_url=config.CORE_API, timeout=10, headers=_auth_headers(path)) as client:
        r = await client.get(path)
        r.raise_for_status()
        return r.json()


async def api_post(path: str, body: dict) -> dict:
    """POST request to Core API. Raises HTTPException with API error detail."""
    async with httpx.AsyncClient(base_url=config.CORE_API, timeout=10, headers=_auth_headers(path)) as client:
        r = await client.post(path, json=body)
        if not r.is_success:
            try:
                err = r.json()
                detail = err.get("detail", f"API error {r.status_code}")
            except Exception:
                detail = f"API error {r.status_code}"
            raise HTTPException(status_code=r.status_code, detail=detail)
        return r.json()
