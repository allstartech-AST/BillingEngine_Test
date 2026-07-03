import json
import os
from pathlib import Path
from typing import Any, List
from pydantic import BaseModel, Field

from app.config import gemini_api_key, gemini_audit_model, load_env_files

load_env_files()

class CptVerificationResponse(BaseModel):
    is_supported: bool = Field(description="True if supported, false if rejected")
    reasoning: str = Field(description="1-2 short sentences explaining why")
    region: str = Field(description="The body part, or empty string if unknown")
    region_confidence: int = Field(description="0 to 100")

class ModifierResponse(BaseModel):
    suggested_modifiers: List[str] = Field(description="List of suggested CPT/HCPCS modifiers")
    reasoning: str = Field(description="A very short, simple phrase explaining why, e.g. 'it was performed on a separate anatomical region'")

class SuggestedCptItem(BaseModel):
    cpt_code: str = Field(description="The suggested CPT code")
    reasoning: str = Field(description="Why this code is supported by the transcript")

class SuggestedCptsResponse(BaseModel):
    suggested_cpts: List[SuggestedCptItem] = Field(description="List of suggested CPT codes")



# We will initialize the client lazily
_client = None
_kb_cache = None


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=gemini_api_key())
    return _client


from app.engine.loader import MetadataStore

def _build_kb_context(store: MetadataStore, *cpts: str) -> str:
    kb_text = []
    if not cpts:
        kb_text.append("--- ENTIRE MEDEXA CPT DICTIONARY ---")
        lines = []
        for code, entry in store.medexa.items():
            label = entry.get("label", "")
            triggers = ", ".join(entry.get("trigger_phrases", []))
            lines.append(f"- {code}: {label} (Triggers: {triggers})")
        kb_text.append("\n".join(lines))
        return "\n\n".join(kb_text)

    for cpt in cpts:
        if not cpt:
            continue
        cpt = cpt.strip()
        kb_text.append(f"--- KNOWLEDGE BASE FOR CPT {cpt} ---")
        
        # General Info
        if store.knows_cpt(cpt):
            kb_text.append(f"General Info: {json.dumps(store.general.get(cpt, {}))}")
            
        # PTP Bundles
        ptp_info = store.ptp.get(cpt)
        if ptp_info:
            kb_text.append(f"NCCI PTP Edit Rules: {json.dumps(ptp_info)}")
            
        # MUE Limits
        mue_info = store.mue.get(cpt)
        if mue_info:
            kb_text.append(f"MUE Limits: {json.dumps(mue_info)}")
            
        # AOC Info
        aoc_info = store.aoc.get(cpt)
        if aoc_info:
            kb_text.append(f"AOC Requirements: {json.dumps(aoc_info)}")
            
        # Medexa Info
        medexa_info = store.medexa.get(cpt)
        if medexa_info:
            kb_text.append(f"Medexa Info: {json.dumps(medexa_info)}")
            
    return "\n\n".join(kb_text)


async def verify_cpt_async(
    cpt_code: str, cpt_description: str, transcript: str, store: MetadataStore = None
) -> dict[str, Any]:
    """Verifies a CPT code based on transcript context."""
    client = _get_client()
    from google.genai import types

    kb_context = _build_kb_context(store, cpt_code) if store else ""

    prompt = f"""You are an expert medical billing AI with professional knowledge of which words are used in natural conversations to describe treatments. 
Strictly adhere to any rules provided in the knowledge base below.

{kb_context}

Task: Verify if the detected CPT code is supported by the transcript.
CPT Code: {cpt_code}
Description: {cpt_description}

Transcript:
{transcript}

Analyze the transcript and determine if this CPT code was actually performed.
Provide your reasoning in 1-2 short sentences.
Also, extract the anatomical region or body part being treated (e.g., "Right Shoulder", "Lumbar Spine", "Left Knee"). 
Provide a confidence score for the region extraction (0-100). If you are not sure, give a low confidence.

Output JSON with exactly these keys:
"is_supported": boolean (true if supported, false if rejected)
"reasoning": string
"region": string (the body part, or empty string if unknown)
"region_confidence": integer (0 to 100)
"""

    try:
        response = await client.aio.models.generate_content(
            model=gemini_audit_model(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CptVerificationResponse,
                temperature=0.2,
            ),
        )
        print("GEMINI CPT RESPONSE:", response.text)
        return json.loads(response.text)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"is_supported": True, "reasoning": f"Failed to parse AI response: {e}", "region": "", "region_confidence": 0}


async def suggest_modifiers_async(
    primary_cpt: str, bundled_cpt: str, transcript: str, store: MetadataStore = None
) -> dict[str, Any]:
    """Suggests top 3 modifiers for an NCCI conflict."""
    client = _get_client()
    from google.genai import types

    kb_context = _build_kb_context(store, primary_cpt, bundled_cpt) if store else ""

    prompt = f"""You are an expert medical billing AI with a complete knowledge of bundling issues that occur in billing. 
Strictly adhere to any rules provided in the knowledge base below.

{kb_context}

Task: An NCCI conflict exists between {primary_cpt} (Primary) and {bundled_cpt} (Bundled). 
Read the transcript sentences fed as of yet to determine if the bundled CPT was a distinct procedural service, performed on a separate structure, or during a separate encounter.

Transcript (sentences fed as of yet):
{transcript}

Common Modifiers:
- 59: Distinct Procedural Service (this will be used when the 4 X modifiers dont seem likely)
- XE: Separate Encounter
- XS: Separate Structure / Organ
- XP: Separate Practitioner
- XU: Unusual Non-Overlapping Service

Based on the transcript, select the best up to 3 modifiers to append to {bundled_cpt} to bypass the bundle.
Output JSON with these keys:
"suggested_modifiers": list of strings (e.g., ["XS", "59"])
"reasoning": string (a very short, simple phrase explaining why, e.g. "it was performed on a separate anatomical region")
"""

    try:
        response = await client.aio.models.generate_content(
            model=gemini_audit_model(),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ModifierResponse,
                temperature=0.2,
            ),
        )
        print("GEMINI MODIFIER RESPONSE:", response.text)
        return json.loads(response.text)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"suggested_modifiers": ["59"], "reasoning": f"Failed to parse AI response: {e}"}


async def suggest_missing_cpts_async(
    transcript: str, existing_cpts: list[str], store: MetadataStore
) -> dict[str, Any]:
    """Suggests missing CPT codes from the transcript using Medexa lookup."""
    client = _get_client()
    from google.genai import types

    kb_context = _build_kb_context(store)

    prompt = f"""You are an expert medical billing AI specialized in clinical natural language processing. 
    You excel at translating casual, conversational descriptions of treatments into precise CPT codes. 
    Carefully analyze the following doctor-patient transcript to identify all billable procedures, evaluations, and therapies. 
{kb_context}

Task: Review the transcript and identify any therapeutic services that correspond to the CPT codes in the Medexa Dictionary above, but are NOT already in the list of existing CPTs.

Existing CPTs already detected: {existing_cpts}

Transcript:
{transcript}

Output only CPT codes that are explicitly supported by the transcript and are present in the Medexa Dictionary.
"""

    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SuggestedCptsResponse,
                temperature=0.2,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"suggested_cpts": []}


async def enrich_conflicts_with_ai(state, store: MetadataStore) -> None:
    for conflict in state.conflicts:
        if conflict.conflict_type == "bypassable_bundle" and not conflict.ai_enriched:
            try:
                res = await suggest_modifiers_async(
                    conflict.column_one_code, 
                    conflict.column_two_code, 
                    state.whole_transcript,
                    store
                )
                mods = res.get("suggested_modifiers", [])
                if mods:
                    for rec in conflict.recommendations:
                        if rec.action == "apply_modifier":
                            rec.modifiers = mods
                            rec.summary = f"✨ AI Suggests: {res.get('reasoning', '')}\n\n" + rec.summary
                conflict.ai_enriched = True
            except Exception:
                conflict.ai_enriched = True # Prevent infinite retries on failure

import asyncio
import threading
_session_locks: dict[str, asyncio.Lock] = {}

def _get_session_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]

async def _ai_enrichment_worker(session_id: str, store: MetadataStore):
    lock = _get_session_lock(session_id)
    # If already locked, another task is running. We still want to queue this task,
    # so that it runs AFTER the current one finishes, to pick up any new CPTs/conflicts.
    async with lock:
        try:
            from app.engine.realtime.handlers_session import get_session, save_session, _refresh_conflicts, _apply_conflict_pending, _recalculate_units
            state = get_session(session_id)
            
            # Loop until no more unverified CPTs or unenriched conflicts are found
            while True:
                made_progress = False
                _refresh_conflicts(state, store)
                
                # 1. Verify unverified CPTs
                for row in state.cpts:
                    if getattr(row, "ai_supported", None) is None:
                        try:
                            res = await verify_cpt_async(
                                row.cpt_code, 
                                store.description(row.cpt_code) if store.knows_cpt(row.cpt_code) else row.cpt_code, 
                                state.whole_transcript,
                                store
                            )
                            row.ai_supported = res.get("is_supported")
                            row.ai_reasoning = res.get("reasoning", "")
                            if res.get("region_confidence", 0) >= 80 and res.get("region"):
                                row.region = res.get("region")
                        except Exception:
                            row.ai_supported = False
                            row.ai_reasoning = "Failed to parse AI response"
                        made_progress = True
                
                # 2. Enrich conflicts
                for conflict in state.conflicts:
                    if conflict.conflict_type == "bypassable_bundle" and not conflict.ai_enriched:
                        try:
                            res = await suggest_modifiers_async(
                                conflict.column_one_code, 
                                conflict.column_two_code, 
                                state.whole_transcript,
                                store
                            )
                            mods = res.get("suggested_modifiers", [])
                            for rec in conflict.recommendations:
                                if rec.action == "apply_modifier":
                                    rec.modifiers = mods
                                    if mods:
                                        mod_str = "/".join(mods)
                                        rec.summary = f"AI Suggestion: {conflict.column_two_code} has a bundle conflict with {conflict.column_one_code}. Apply modifier {mod_str} because {res.get('reasoning', '').lower()}"
                                    else:
                                        rec.summary = f"AI Suggestion: {conflict.column_two_code} has a bundle conflict with {conflict.column_one_code}, but no modifier applies because {res.get('reasoning', '').lower()}"
                            conflict.ai_enriched = True
                        except Exception:
                            conflict.ai_enriched = True
                        made_progress = True
                        
                # 3. Check for missing CPTs sequentially
                current_pointer = getattr(state, "last_cpt_suggestion_length", 0)
                while len(state.whole_transcript) > current_pointer + 150:
                    next_pointer = min(current_pointer + 200, len(state.whole_transcript))
                    
                    # Try to align next_pointer to a space to avoid cutting words
                    space_index = state.whole_transcript.find(" ", next_pointer)
                    if space_index != -1 and space_index < next_pointer + 50:
                        next_pointer = space_index + 1
                    elif space_index == -1:
                        next_pointer = len(state.whole_transcript)
                        
                    transcript_slice = state.whole_transcript[:next_pointer]
                    existing_cpts = [r.cpt_code for r in state.cpts]
                    try:
                        res = await suggest_missing_cpts_async(transcript_slice, existing_cpts, store)
                        suggested = res.get("suggested_cpts", [])
                        if suggested:
                            from app.models.live import LiveCptRow
                            from app.engine.realtime.helpers import _next_sequence, _apply_icd_validation, _sync_row_messages
                            for item in suggested:
                                code = item.get("cpt_code")
                                if code and store.knows_cpt(code) and code not in existing_cpts:
                                    row = LiveCptRow(
                                        cpt_code=code,
                                        sequence=_next_sequence(state.cpts),
                                        lifecycle="ai_suggested",
                                        is_timed=store.is_timed(code),
                                        billing_status="pending_therapist_review",
                                        rule_message="AI suggested code based on transcript.",
                                        ai_supported=True,
                                        ai_reasoning=item.get("reasoning", "")
                                    )
                                    _apply_icd_validation(row, state.icds, store)
                                    _sync_row_messages(row)
                                    state.cpts.append(row)
                                    existing_cpts.append(code)
                                    made_progress = True
                    except Exception:
                        pass
                    current_pointer = next_pointer
                    state.last_cpt_suggestion_length = current_pointer
                        
                if not made_progress:
                    break
            
            # 3. Refresh and save
            _refresh_conflicts(state, store)
            _apply_conflict_pending(state)
            _recalculate_units(state, store)
            save_session(state)
            
        except Exception as e:
            import traceback
            traceback.print_exc()

def launch_ai_enrichment_task(session_id: str, store: MetadataStore) -> None:
    """Schedule AI enrichment without assuming a running event loop."""
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            loop.create_task(_ai_enrichment_worker(session_id, store))
            return
    except RuntimeError:
        pass

    def _run_worker() -> None:
        asyncio.run(_ai_enrichment_worker(session_id, store))

    threading.Thread(
        target=_run_worker,
        name=f"ai-enrichment-{session_id[:8]}",
        daemon=True,
    ).start()
