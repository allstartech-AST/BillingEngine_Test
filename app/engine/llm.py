import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# We will initialize the client lazily
_client = None
_kb_cache = None


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return _client


from app.engine.loader import MetadataStore

def _build_kb_context(store: MetadataStore, *cpts: str) -> str:
    kb_text = []
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
            
    return "\n\n".join(kb_text)


async def verify_cpt_async(
    cpt_code: str, cpt_description: str, transcript: str, store: MetadataStore = None
) -> dict[str, Any]:
    """Verifies a CPT code based on transcript context."""
    client = _get_client()
    from google.genai import types

    kb_context = _build_kb_context(store, cpt_code) if store else ""

    prompt = f"""You are an expert medical billing AI. 
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
            model="gemini-flash-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
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

    prompt = f"""You are an expert medical billing AI. 
Strictly adhere to any rules provided in the knowledge base below.

{kb_context}

Task: An NCCI conflict exists between {primary_cpt} (Primary) and {bundled_cpt} (Bundled). 
Read the transcript to determine if the bundled CPT was a distinct procedural service, performed on a separate structure, or during a separate encounter.

Transcript:
{transcript}

Common Modifiers:
- 59: Distinct Procedural Service
- XE: Separate Encounter
- XS: Separate Structure / Organ
- XP: Separate Practitioner
- XU: Unusual Non-Overlapping Service

Based on the transcript, select the best up to 3 modifiers to append to {bundled_cpt} to bypass the bundle.
Output JSON with these keys:
"suggested_modifiers": list of strings (e.g., ["XS", "59"])
"reasoning": string (1-2 sentences explaining why)
"""

    try:
        response = await client.aio.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        print("GEMINI MODIFIER RESPONSE:", response.text)
        return json.loads(response.text)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"suggested_modifiers": ["59"], "reasoning": f"Failed to parse AI response: {e}"}


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
                            if mods:
                                for rec in conflict.recommendations:
                                    if rec.action == "apply_modifier":
                                        rec.modifiers = mods
                                        rec.summary = f"✨ AI Suggests: {res.get('reasoning', '')}\n\n" + rec.summary
                            conflict.ai_enriched = True
                        except Exception:
                            conflict.ai_enriched = True
                        made_progress = True
                        
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

def launch_ai_enrichment_task(session_id: str, store: MetadataStore):
    asyncio.create_task(_ai_enrichment_worker(session_id, store))
