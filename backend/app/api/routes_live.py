from fastapi import APIRouter, HTTPException
from app.engine.loader import load_metadata
from app.engine.realtime.handlers_session import create_live_session, get_live_session, on_session_end, on_sentence_fed
from app.engine.realtime.handlers_icd import on_icd_detected
from app.engine.realtime.handlers_cpt import on_cpt_detected, on_cpt_start, on_cpt_end, on_cpt_pause, on_cpt_resume
from app.engine.realtime.handlers_modifier import on_modifier_action
from app.models.live import (
    LiveClientInfo,
    LiveCptDetectRequest,
    LiveCptDurationRequest,
    LiveCptEndRequest,
    LiveIcdRequest,
    LiveModifierRequest,
    LiveSessionCreateRequest,
    LiveSessionResponse,
    LiveTranscriptSentenceRequest,
)

router = APIRouter(prefix="/live/session", tags=["live"])

def _live_store():
    try:
        return load_metadata()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Billing metadata failed to load",
                "error": str(exc),
                "type": type(exc).__name__,
            },
        ) from exc


@router.post("", response_model=LiveSessionResponse)
async def live_session_create(body: LiveSessionCreateRequest) -> LiveSessionResponse:
    store = _live_store()
    client = LiveClientInfo(client_name=body.client_name, client_id=body.client_id)
    return create_live_session(client, body.billing_rule, store)


@router.get("/{session_id}", response_model=LiveSessionResponse)
async def live_session_get(session_id: str) -> LiveSessionResponse:
    store = _live_store()
    return get_live_session(session_id, store)


@router.post("/{session_id}/icd", response_model=LiveSessionResponse)
async def live_session_icd(session_id: str, body: LiveIcdRequest) -> LiveSessionResponse:
    store = _live_store()
    return on_icd_detected(session_id, body.icd10_code, store)


@router.post("/{session_id}/cpt/detect", response_model=LiveSessionResponse)
async def live_session_cpt_detect(session_id: str, body: LiveCptDetectRequest) -> LiveSessionResponse:
    store = _live_store()
    return on_cpt_detected(session_id, body.cpt_code, store)


@router.post("/{session_id}/transcript/sentence", response_model=LiveSessionResponse)
async def live_session_sentence(session_id: str, body: LiveTranscriptSentenceRequest) -> LiveSessionResponse:
    store = _live_store()
    return on_sentence_fed(session_id, body.sentence, store)


@router.post("/{session_id}/cpt/start", response_model=LiveSessionResponse)
async def live_session_cpt_start(session_id: str, body: LiveCptDetectRequest) -> LiveSessionResponse:
    store = _live_store()
    return on_cpt_start(session_id, body.cpt_code, store)


@router.post("/{session_id}/cpt/end", response_model=LiveSessionResponse)
async def live_session_cpt_end(session_id: str, body: LiveCptEndRequest) -> LiveSessionResponse:
    store = _live_store()
    return on_cpt_end(session_id, body.cpt_code, body.duration_minutes, store)


@router.post("/{session_id}/cpt/pause", response_model=LiveSessionResponse)
async def live_session_cpt_pause(session_id: str, body: LiveCptDurationRequest) -> LiveSessionResponse:
    store = _live_store()
    return on_cpt_pause(session_id, body.cpt_code, body.duration_minutes, store)


@router.post("/{session_id}/cpt/resume", response_model=LiveSessionResponse)
async def live_session_cpt_resume(session_id: str, body: LiveCptDetectRequest) -> LiveSessionResponse:
    store = _live_store()
    return on_cpt_resume(session_id, body.cpt_code, store)


@router.post("/{session_id}/modifier", response_model=LiveSessionResponse)
async def live_session_modifier(session_id: str, body: LiveModifierRequest) -> LiveSessionResponse:
    store = _live_store()
    return on_modifier_action(session_id, body.conflict_id, body.action, body.modifier, store)


@router.post("/{session_id}/end", response_model=LiveSessionResponse)
async def live_session_end(session_id: str) -> LiveSessionResponse:
    store = _live_store()
    return on_session_end(session_id, store)
