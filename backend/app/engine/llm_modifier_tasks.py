"""OpenAI NCCI modifier suggestions for live sessions."""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING, Any, List

from pydantic import BaseModel, Field

from app.config import load_env_files
from app.engine.llm_kb import build_kb_context
from app.engine.llm_provider import generate_json_pydantic, is_configured
from app.engine.llm_quota import is_quota_error, mark_quota_exhausted
from app.engine.loader import MetadataStore

if TYPE_CHECKING:
    from app.engine.llm_session_thread import LiveEnrichmentThread

load_env_files()

logger = logging.getLogger(__name__)


class ModifierResponse(BaseModel):
    suggested_modifiers: List[str] = Field(description="List of suggested CPT/HCPCS modifiers")
    reasoning: str = Field(
        description=(
            "A very short, simple phrase explaining why, "
            "e.g. 'it was performed on a separate anatomical region'"
        )
    )


def _modifier_prompt(
    primary_cpt: str,
    bundled_cpt: str,
    transcript: str,
    kb_context: str,
) -> str:
    return f"""You are an expert medical billing AI with a complete knowledge of bundling issues that occur in billing. 
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
"""


def _modifier_prompt_threaded(
    primary_cpt: str,
    bundled_cpt: str,
    transcript: str,
    ptp_context: str,
) -> str:
    ptp_block = f"\n{ptp_context}\n" if ptp_context else "\n"
    return f"""You are an expert medical billing AI with a complete knowledge of bundling issues that occur in billing. 
{ptp_block}
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
"""


async def suggest_modifiers_async(
    primary_cpt: str,
    bundled_cpt: str,
    transcript: str,
    store: MetadataStore = None,
    *,
    thread: "LiveEnrichmentThread | None" = None,
) -> dict[str, Any]:
    """Suggests modifiers for an NCCI conflict."""
    if not is_configured():
        return {"suggested_modifiers": [], "reasoning": "OpenAI API key is not configured."}

    try:
        if thread is not None:
            ptp_context = thread.compact_ptp_pair(primary_cpt, bundled_cpt)
            prompt = _modifier_prompt_threaded(
                primary_cpt, bundled_cpt, transcript, ptp_context
            )
            result = await thread.complete_json(prompt, ModifierResponse, temperature=0.2)
        else:
            kb_context = build_kb_context(store, primary_cpt, bundled_cpt) if store else ""
            prompt = _modifier_prompt(primary_cpt, bundled_cpt, transcript, kb_context)
            result = await generate_json_pydantic(
                user_prompt=prompt,
                response_model=ModifierResponse,
                temperature=0.2,
            )
        logger.info("OpenAI modifier response for %s/%s: %s", primary_cpt, bundled_cpt, result)
        return result
    except Exception as e:
        if is_quota_error(e):
            mark_quota_exhausted(e)
        traceback.print_exc()
        return {"suggested_modifiers": ["59"], "reasoning": f"Failed to parse AI response: {e}"}
