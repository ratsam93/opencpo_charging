"""Charge App configuration — all settings from environment variables."""
import os

CORE_API = os.getenv("OCPP_CORE_API_URL", os.getenv("OCPP_CORE_API", "http://localhost:8000"))
SKIN = os.getenv("SKIN", "default")
PLUGINS = os.getenv("PLUGINS", "receipts,account").split(",")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", os.getenv("PORT", "8003")))
APP_TITLE = os.getenv("APP_TITLE", "OCPP Charge")
JWT_SECRET = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    import secrets as _secrets
    JWT_SECRET = _secrets.token_hex(32)
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "JWT_SECRET not set — using random secret (sessions won't persist across restarts)"
    )


# ── Security settings ─────────────────────────────────────────────────────
PUBLIC_URL = os.getenv("PUBLIC_URL", "")

def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")

# Secure cookies by default whenever the public URL is https.
COOKIE_SECURE = _env_bool("COOKIE_SECURE", PUBLIC_URL.lower().startswith("https://"))

# X-Client-Cert-Serial is only meaningful when set by a TLS-terminating reverse
# proxy that verified a client certificate. Any client can send it, so it is
# IGNORED unless this is explicitly enabled. The proxy must strip the header
# from incoming requests and set it itself.
TRUST_CLIENT_CERT_HEADER = _env_bool("TRUST_CLIENT_CERT_HEADER", False)

# Sessions may only be read/stopped/cancelled by the browser that created them
# (signed cookie) or by the logged-in account that owns them.
SESSION_OWNERSHIP_CHECK = _env_bool("SESSION_OWNERSHIP_CHECK", True)
