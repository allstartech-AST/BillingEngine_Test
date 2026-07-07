from contextlib import asynccontextmanager
import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import llm_provider_name, openai_api_key, load_env_files
from app.engine.loader import load_metadata
from app.engine.llm_enrichment import register_enrichment_event_loop
from app.api import live_router, batch_router, system_router, audit_router

load_env_files()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    register_enrichment_event_loop(asyncio.get_running_loop())
    try:
        load_metadata()
    except Exception as exc:
        _app.state.metadata_error = str(exc)
        raise
    _app.state.metadata_error = None
    if not openai_api_key():
        provider_name = llm_provider_name()
        api_key_name = "GROQ_API_KEY" if provider_name == "Groq" else "OPENAI_API_KEY"
        logger.warning(
            f"{api_key_name} is not set. AI suggestions, summary validation, "
            f"and LLM audit features will be unavailable. Add your {provider_name} key to backend/.env.local "
            "and restart the server."
        )
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
            "hint": "Check the uvicorn terminal for the full traceback. Start the server from backend/: python -m uvicorn app.main:app --reload",
        },
    )
