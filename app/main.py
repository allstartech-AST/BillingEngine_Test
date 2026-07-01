from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.engine.loader import load_metadata
from app.api import live_router, batch_router, system_router

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        load_metadata()
    except Exception as exc:
        _app.state.metadata_error = str(exc)
        raise
    _app.state.metadata_error = None
    yield


app = FastAPI(title="Billing Engine", version="1.0.0", lifespan=lifespan)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(system_router)
app.include_router(live_router)
app.include_router(batch_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request, exc):
    if isinstance(exc, HTTPException):
        raise exc
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "detail": str(exc),
            "type": type(exc).__name__,
            "hint": "Check the uvicorn terminal for the full traceback. Common fix: restart from ProperData with python -m uvicorn app.main:app --reload",
        },
    )
