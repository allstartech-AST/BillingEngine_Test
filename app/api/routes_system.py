from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

router = APIRouter(tags=["system"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


REACT_DIR = STATIC_DIR / "react"


@router.get("/")
def root():
    return RedirectResponse(url="/prototype")


@router.get("/dashboard")
@router.get("/dashboard/{full_path:path}")
def dashboard_spa(full_path: str = ""):
    index = REACT_DIR / "index.html"
    if full_path:
        asset = REACT_DIR / full_path
        if asset.is_file():
            return FileResponse(asset)
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    raise HTTPException(
        status_code=404,
        detail="React dashboard not built. Run: cd frontend && npm install && npm run build",
    )


@router.get("/prototype")
def prototype_page():
    page = STATIC_DIR / "prototype.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Prototype page not found")
    return FileResponse(page, headers={"Cache-Control": "no-cache"})


@router.get("/static/prototype.html")
def prototype_static_redirect():
    return RedirectResponse(url="/prototype")


@router.get("/health")
def health(request: Request):
    error = getattr(request.app.state, "metadata_error", None)
    payload = {
        "status": "ok" if not error else "degraded",
        "live_api": True,
        "billing_api": True,
    }
    if error:
        payload["metadata_error"] = error
    return payload
