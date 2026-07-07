"""OpenAI CPT verification and missing-code suggestion for live sessions."""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING, Any, List

from pydantic import BaseModel, Field

from app.config import load_env_files
from app.engine.llm_kb import build_compact_medexa_reference, build_kb_context
from app.engine.llm_provider import generate_json_pydantic, is_configured
from app.engine.llm_quota import is_quota_error, mark_quota_exhausted
from app.engine.loader import MetadataStore

if TYPE_CHECKING:
    from app.engine.llm_session_thread import LiveEnrichmentThread

load_env_files()

logger = logging.getLogger(__name__)


class CptVerificationResponse(BaseModel):
    is_supported: bool = Field(description="True if supported, false if rejected")
    reasoning: str = Field(description="1-2 short sentences explaining why")
    region: str = Field(description="The body part, or empty string if unknown")
    region_confidence: int = Field(description="0 to 100")


class SuggestedCptItem(BaseModel):
    cpt_code: str = Field(description="The suggested CPT code")
    reasoning: str = Field(description="Why this code is supported by the transcript")


class SuggestedCptsResponse(BaseModel):
    suggested_cpts: List[SuggestedCptItem] = Field(description="List of suggested CPT codes")


def _verify_prompt(cpt_code: str, cpt_description: str, transcript: str, kb_context: str) -> str:
    return f"""You are an expert medical billing AI with professional knowledge of which words are used in natural conversations to describe treatments. 
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
"""


def _verify_prompt_threaded(cpt_code: str, cpt_description: str, transcript: str) -> str:
    return f"""Task: Verify if the detected CPT code is supported by the transcript.
CPT Code: {cpt_code}
Description: {cpt_description}

Transcript:
{transcript}

Analyze the transcript and determine if this CPT code was actually performed.
Provide your reasoning in 1-2 short sentences.
Also, extract the anatomical region or body part being treated (e.g., "Right Shoulder", "Lumbar Spine", "Left Knee"). 
Provide a confidence score for the region extraction (0-100). If you are not sure, give a low confidence.
"""


async def verify_cpt_async(
    cpt_code: str,
    cpt_description: str,
    transcript: str,
    store: MetadataStore = None,
    *,
    thread: "LiveEnrichmentThread | None" = None,
) -> dict[str, Any]:
    """Verifies a CPT code based on transcript context."""
    if not is_configured():
        return {
            "is_supported": None,
            "reasoning": "OpenAI API key is not configured.",
            "region": "",
            "region_confidence": 0,
        }

    try:
        if thread is not None:
            prompt = _verify_prompt_threaded(cpt_code, cpt_description, transcript)
            result = await thread.complete_json(prompt, CptVerificationResponse, temperature=0.2)
        else:
            kb_context = build_kb_context(store, cpt_code) if store else ""
            prompt = _verify_prompt(cpt_code, cpt_description, transcript, kb_context)
            result = await generate_json_pydantic(
                user_prompt=prompt,
                response_model=CptVerificationResponse,
                temperature=0.2,
            )
        logger.info("OpenAI CPT verify response for %s: %s", cpt_code, result)
        return result
    except Exception as e:
        if is_quota_error(e):
            mark_quota_exhausted(e)
        traceback.print_exc()
        return {
            "is_supported": True,
            "reasoning": f"Failed to parse AI response: {e}",
            "region": "",
            "region_confidence": 0,
        }


def _suggest_missing_prompt(
    transcript: str,
    existing_cpts: list[str],
    kb_context: str,
    hints_suffix: str,
) -> str:
    return f"""You are an expert medical billing AI specialized in clinical natural language processing. 
    You excel at translating casual, conversational descriptions of treatments into precise CPT codes. 
    Carefully analyze the following doctor-patient transcript to identify all billable procedures, evaluations, and therapies. 
{kb_context}

Task: Review the transcript and identify any therapeutic services that correspond to the CPT codes in the Medexa Dictionary above, but are NOT already in the list of existing CPTs.

Existing CPTs already detected: {existing_cpts}

Transcript:
{transcript}{hints_suffix}

Output only CPT codes that are explicitly supported by the transcript and are present in the Medexa Dictionary.
"""


def _suggest_missing_prompt_threaded(
    transcript: str,
    existing_cpts: list[str],
    hints_suffix: str,
) -> str:
    return f"""You are an expert medical billing AI specialized in clinical natural language processing. 
    You excel at translating casual, conversational descriptions of treatments into precise CPT codes. 
    Carefully analyze the following doctor-patient transcript to identify all billable procedures, evaluations, and therapies. 

Task: Review the transcript and identify any therapeutic services that correspond to the CPT codes in the Medexa Dictionary above, but are NOT already in the list of existing CPTs.

Existing CPTs already detected: {existing_cpts}

Transcript:
{transcript}{hints_suffix}

Output only CPT codes that are explicitly supported by the transcript and are present in the Medexa Dictionary.
"""


async def suggest_missing_cpts_async(
    transcript: str,
    existing_cpts: list[str],
    store: MetadataStore,
    lexical_hints: list[str] | None = None,
    *,
    thread: "LiveEnrichmentThread | None" = None,
) -> dict[str, Any]:
    """Suggests missing CPT codes from the transcript using Medexa lookup."""
    if not is_configured():
        return {"suggested_cpts": []}

    hints_suffix = ""
    if lexical_hints:
        hints_suffix = "\n" + "\n".join(lexical_hints)

    try:
        if thread is not None:
            prompt = _suggest_missing_prompt_threaded(
                transcript, existing_cpts, hints_suffix
            )
            result = await thread.complete_json(prompt, SuggestedCptsResponse, temperature=0.2)
        else:
            kb_context = build_compact_medexa_reference(store)
            prompt = _suggest_missing_prompt(
                transcript, existing_cpts, kb_context, hints_suffix
            )
            result = await generate_json_pydantic(
                user_prompt=prompt,
                response_model=SuggestedCptsResponse,
                temperature=0.2,
            )
        logger.info("OpenAI CPT suggestion response: %s", result)
        return result
    except Exception as e:
        if is_quota_error(e):
            mark_quota_exhausted(e)
        traceback.print_exc()
        return {"suggested_cpts": []}
