"""OpenAI CPT verification and missing-code suggestion for live sessions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List

from pydantic import BaseModel, Field

from app.config import load_env_files
from app.engine.conflict_evaluation import codes_hard_rejected_if_added
from app.engine.llm_kb import (
    build_compact_medexa_reference,
    build_kb_context,
    build_suggest_conflict_context,
)
from app.engine.llm_provider import generate_json_pydantic, is_configured
from app.engine.llm_quota import is_quota_error, mark_quota_exhausted
from app.engine.loader import MetadataStore

if TYPE_CHECKING:
    from app.engine.llm_session_thread import LiveEnrichmentThread

load_env_files()

logger = logging.getLogger(__name__)

CPT_SYSTEM_PROMPT = """You are an expert outpatient PT/OT/SLP medical-coding assistant.
Use only CPT/HCPCS codes present in the supplied Medexa knowledge base.
Require transcript evidence that the service was actually performed; honor each entry's
trigger phrases, required context, and exclusions. Do not infer engine-selected codes
with empty trigger phrases unless the task supplies the required duration, area, parent,
or clinician-selection evidence. Never suggest a code that would be auto-rejected because
of hard NCCI bundles, missing add-on parent codes, or MUE-zero limits relative to the
existing session CPTs. Return only the requested structured JSON."""

SUGGEST_CONFLICT_INSTRUCTION = (
    "Only suggest codes that can bill alongside the existing session CPTs without being "
    "auto-rejected. Skip any code listed in the conflict guardrails or that would hard-bundle "
    "into an existing code."
)

EXACT_QUOTE_INSTRUCTION = (
    "For each suggested CPT, extract the exact 3-7 consecutive words from the transcript "
    "that justify the suggestion. Return that substring verbatim in exact_quote. Do not paraphrase."
)


def filter_suggestable_cpts(
    suggested: list[dict[str, Any]],
    existing_cpts: list[str],
    store: MetadataStore,
) -> list[dict[str, Any]]:
    """Drop AI suggestions that would be hard-removed if added to the session."""
    active = {code for code in existing_cpts if code}
    candidates = [
        (item.get("cpt_code") or "").strip()
        for item in suggested
        if item.get("cpt_code")
    ]
    rejected = codes_hard_rejected_if_added(active, candidates, store)
    if not rejected:
        return suggested

    kept: list[dict[str, Any]] = []
    for item in suggested:
        code = (item.get("cpt_code") or "").strip()
        if code in rejected:
            logger.info(
                "Dropped AI CPT suggestion %s: %s",
                code,
                rejected[code],
            )
            continue
        kept.append(item)
    return kept


class CptVerificationResponse(BaseModel):
    is_supported: bool = Field(description="True if supported, false if rejected")
    reasoning: str = Field(description="1-2 short sentences explaining why")
    region: str = Field(description="The body part, or empty string if unknown")
    region_confidence: int = Field(description="0 to 100")


class SuggestedCptItem(BaseModel):
    cpt_code: str = Field(description="The suggested CPT code")
    reasoning: str = Field(description="Why this code is supported by the transcript")
    exact_quote: str = Field(
        default="",
        description="Exact 3-7 word transcript substring supporting this suggestion",
    )


class SuggestedCptsResponse(BaseModel):
    suggested_cpts: List[SuggestedCptItem] = Field(description="List of suggested CPT codes")


def _verify_prompt(cpt_code: str, cpt_description: str, transcript: str, kb_context: str) -> str:
    return f"""Strictly adhere to the knowledge base below.

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
                system_prompt=CPT_SYSTEM_PROMPT,
                temperature=0.2,
            )
        logger.info("OpenAI CPT verify response for %s: %s", cpt_code, result)
        return result
    except Exception as e:
        if is_quota_error(e):
            mark_quota_exhausted(e)
            logger.warning("CPT verify skipped for %s due to rate limit: %s", cpt_code, e)
        else:
            logger.exception("CPT verify failed for %s", cpt_code)
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
    conflict_context: str = "",
) -> str:
    conflict_block = f"\n{conflict_context}\n" if conflict_context else ""
    return f"""Carefully analyze the following transcript for explicitly supported billable procedures, evaluations, and therapies.
{kb_context}
{conflict_block}
{SUGGEST_CONFLICT_INSTRUCTION}

Task: Review the transcript and identify any therapeutic services that correspond to the CPT codes in the Medexa Dictionary above, but are NOT already in the list of existing CPTs.

Existing CPTs already detected: {existing_cpts}

Transcript:
{transcript}{hints_suffix}

Output only CPT codes that are explicitly supported by the transcript, are present in the Medexa Dictionary, and would not be auto-rejected by the conflict guardrails above.

{EXACT_QUOTE_INSTRUCTION}
"""


def _suggest_missing_prompt_threaded(
    transcript: str,
    existing_cpts: list[str],
    hints_suffix: str,
    conflict_context: str = "",
) -> str:
    conflict_block = f"\n{conflict_context}\n" if conflict_context else ""
    return f"""Carefully analyze the following transcript for explicitly supported billable procedures, evaluations, and therapies.
{conflict_block}
{SUGGEST_CONFLICT_INSTRUCTION}

Task: Review the transcript and identify any therapeutic services that correspond to the CPT codes in the Medexa Dictionary above, but are NOT already in the list of existing CPTs.

Existing CPTs already detected: {existing_cpts}

Transcript:
{transcript}{hints_suffix}

Output only CPT codes that are explicitly supported by the transcript, are present in the Medexa Dictionary, and would not be auto-rejected by the conflict guardrails above.

{EXACT_QUOTE_INSTRUCTION}
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

    conflict_context = build_suggest_conflict_context(store, existing_cpts)

    try:
        if thread is not None:
            prompt = _suggest_missing_prompt_threaded(
                transcript, existing_cpts, hints_suffix, conflict_context
            )
            result = await thread.complete_json(prompt, SuggestedCptsResponse, temperature=0.2)
        else:
            kb_context = build_compact_medexa_reference(store)
            prompt = _suggest_missing_prompt(
                transcript, existing_cpts, kb_context, hints_suffix, conflict_context
            )
            result = await generate_json_pydantic(
                user_prompt=prompt,
                response_model=SuggestedCptsResponse,
                system_prompt=CPT_SYSTEM_PROMPT,
                temperature=0.2,
            )
        suggested = result.get("suggested_cpts", [])
        filtered = filter_suggestable_cpts(suggested, existing_cpts, store)
        result["suggested_cpts"] = filtered
        logger.info("OpenAI CPT suggestion response: %s", result)
        return result
    except Exception as e:
        if is_quota_error(e):
            mark_quota_exhausted(e)
            logger.warning("CPT suggestion skipped due to rate limit: %s", e)
        else:
            logger.warning("CPT suggestion failed: %s", e)
        return {"suggested_cpts": []}
