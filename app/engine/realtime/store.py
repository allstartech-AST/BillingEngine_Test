import uuid

from fastapi import HTTPException

from app.models.live import LiveClientInfo, LiveSessionState


_sessions: dict[str, LiveSessionState] = {}


def create_session(client: LiveClientInfo, billing_rule: str) -> LiveSessionState:
    session_id = str(uuid.uuid4())
    state = LiveSessionState(session_id=session_id, client_info=client, billing_rule=billing_rule)
    _sessions[session_id] = state
    return state


def get_session(session_id: str) -> LiveSessionState:
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Live session {session_id} not found")
    return state


def save_session(state: LiveSessionState) -> LiveSessionState:
    _sessions[state.session_id] = state
    return state


def reset_sessions() -> None:
    """Test helper."""
    _sessions.clear()
