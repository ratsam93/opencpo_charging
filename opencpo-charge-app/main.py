"""OCPP Charge App — PWA for EV drivers."""
import os
import logging

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from core.middleware import inject_context, template_context
from core.security import security_headers
from plugins import discover_plugins

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=config.APP_TITLE, docs_url=None, redoc_url=None)

# ── Static files ──────────────────────────────────────────────────────────
# Skin static served at /skin (takes precedence in templates)
ACTIVE_SKIN = config.SKIN
if not os.path.isdir(f"skins/{ACTIVE_SKIN}/static"):
    logging.getLogger(__name__).error(
        "SKIN %r not found in skins/ — falling back to 'default'", ACTIVE_SKIN)
    ACTIVE_SKIN = "default"
skin_static = f"skins/{ACTIVE_SKIN}/static"
if os.path.isdir(skin_static):
    app.mount("/skin", StaticFiles(directory=skin_static), name="skin")

# Base static always available at /static (home.js, htmx, logos, fallback CSS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Templates ─────────────────────────────────────────────────────────────
# Resolution order: skin templates → plugin templates → base templates
template_dirs = []
skin_templates = f"skins/{ACTIVE_SKIN}/templates"
if os.path.isdir(skin_templates):
    template_dirs.append(skin_templates)
# Add plugin template directories
for plugin_name in config.PLUGINS:
    plugin_tmpl = f"plugins/{plugin_name}/templates"
    if os.path.isdir(plugin_tmpl):
        template_dirs.append(plugin_tmpl)
template_dirs.append("templates")

templates = Jinja2Templates(directory=template_dirs, context_processors=[template_context])
templates.env.globals["app_title"] = config.APP_TITLE
app.state.templates = templates

# ── Health + service worker ───────────────────────────────────────────────
@app.get("/health", include_in_schema=False)
async def health():
    return JSONResponse({"status": "ok", "service": "charge-app"})


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    """Serve the service worker from the site root so its scope is '/'."""
    return FileResponse(
        "static/sw.js", media_type="text/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


# ── Routes ────────────────────────────────────────────────────────────────
from routes import home, charge, auth, session, receipt, qr, push, cert_setup

for router in [home.router, charge.router, auth.router, session.router, receipt.router, qr.router, push.router, cert_setup.router]:
    app.include_router(router)

# ── Plugins ───────────────────────────────────────────────────────────────
for plugin_router in discover_plugins(config.PLUGINS):
    app.include_router(plugin_router)

# ── Middleware ────────────────────────────────────────────────────────────
app.middleware("http")(inject_context)
app.middleware("http")(security_headers)   # added last = outermost: wraps every response

if __name__ == "__main__":
    uvicorn.run("main:app", host=config.APP_HOST, port=config.APP_PORT)
