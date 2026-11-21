"""Per-charger OCPP credentials (management API; requires the management key).

A charger authenticates its WebSocket connection with HTTP Basic auth: user name =
charge point id, password = the secret created here. Passwords are stored only as
bcrypt hashes and are returned exactly once, when created or rotated.
"""
import logging
import secrets

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from security.charger_auth import CP_ID_RE, MIN_PASSWORD_LENGTH, get_authenticator
from state import charger_registry

logger = logging.getLogger(__name__)
router = APIRouter()


class CredentialRequest(BaseModel):
    password: str | None = None   # leave empty to generate a strong one


def _check_id(cp_id: str) -> None:
    if not CP_ID_RE.match(cp_id):
        raise HTTPException(422, "Charge point id must be 1-64 characters of A-Z a-z 0-9 . _ : -")


@router.get("")
async def list_credentials():
    """Which chargers have credentials (never the secrets)."""
    return {"credentials": await get_authenticator().list_credentials()}


@router.post("/{cp_id}")
async def create_or_rotate(cp_id: str, response: Response, body: CredentialRequest | None = None):
    """Create or rotate a charger's password. The plaintext is returned once."""
    _check_id(cp_id)
    password = (body.password if body else None) or secrets.token_urlsafe(24)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(422, f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    await get_authenticator().set_password(cp_id, password)
    logger.info("Charger credentials set for %s", cp_id)
    response.headers["Cache-Control"] = "no-store"
    return {
        "charge_point": cp_id,
        "password": password,
        "note": "Shown once. Configure the charger with user name = charge point id and this password (HTTP Basic).",
    }


@router.delete("/{cp_id}")
async def revoke(cp_id: str):
    """Revoke a charger's credentials and disconnect it if it is connected."""
    _check_id(cp_id)
    if not await get_authenticator().revoke(cp_id):
        raise HTTPException(404, "No active credentials for this charge point")
    disconnected = await charger_registry.disconnect(cp_id)
    logger.warning("Charger credentials revoked for %s (disconnected=%s)", cp_id, disconnected)
    return {"charge_point": cp_id, "revoked": True, "disconnected": disconnected}
