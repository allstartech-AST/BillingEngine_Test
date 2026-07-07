
from app.engine.loader import MetadataStore
from app.models.live import LiveSessionResponse
from app.engine.realtime.store import get_session, save_session
from app.engine.realtime.helpers import (
    _append_icd, _parse_icd_input, _reactivate_session,
    _revalidate_all_cpts_icd, _sync_row_messages, _live_response,
    _reconcile_billing_state_and_save,
)

def on_icd_detected(session_id: str, icd10_code: str, store: MetadataStore) -> LiveSessionResponse:
    state = get_session(session_id)
    _reactivate_session(state)
    before = len(state.icds)
    added: list[str] = []
    for code in _parse_icd_input(icd10_code):
        prev_len = len(state.icds)
        state.icds = _append_icd(state.icds, code)
        if len(state.icds) > prev_len:
            added.append(code)
    _revalidate_all_cpts_icd(state, store)
    for row in state.cpts:
        _sync_row_messages(row)
    _reconcile_billing_state_and_save(state, store)
    if added:
        msg = f"ICD added: {', '.join(added)}."
    elif before == len(state.icds):
        msg = "No new ICD codes (duplicate or empty input)."
    else:
        msg = "ICD list updated."
    return _live_response(state, store, msg)

