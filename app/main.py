from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import load_env_files
from app.engine.loader import load_metadata
from app.api import live_router, batch_router, system_router, audit_router

load_env_files()

logging.basicConfig(level=logging.INFO)

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(system_router)
app.include_router(live_router)
app.include_router(audit_router)
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
