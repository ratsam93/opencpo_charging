"""Receipt routes: receipt screen, JSON data, PDF download."""
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse

import config
from core.api import api_get
from core.security import authorize_session, forbidden, safe_error

router = APIRouter()


@router.get("/receipt/{session_id}", response_class=HTMLResponse)
async def receipt_screen(request: Request, session_id: str):
    templates = request.app.state.templates
    flags = getattr(request.state, "flags", {})
    return templates.TemplateResponse(request, "receipt.html", {
        "session_id": session_id,
        "flags": flags,
        "t": getattr(request.state, "t", {}),
        "lang": getattr(request.state, "lang", "nl"),
    })


@router.get("/api/sessions/{session_id}/receipt")
async def get_receipt(request: Request, session_id: str):
    allowed, data = await authorize_session(request, session_id)
    if not allowed:
        return forbidden()
    try:
        if data is None:
            data = await api_get(f"/api/v1/public/sessions/{session_id}")
        return JSONResponse(data)
    except Exception as e:
        return safe_error(e)


@router.get("/api/sessions/{session_id}/pdf")
async def download_pdf(request: Request, session_id: str):
    """Proxy PDF download from OCPP Core."""
    allowed, _ = await authorize_session(request, session_id)
    if not allowed:
        return forbidden()
    async with httpx.AsyncClient(base_url=config.CORE_API, timeout=30) as client:
        r = await client.get(f"/api/v1/public/sessions/{session_id}/pdf")
        if not r.is_success:
            return RedirectResponse(f"/receipt/{session_id}", status_code=302)
        return Response(
            content=r.content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="laadbon-{session_id[:8]}.pdf"'},
        )
