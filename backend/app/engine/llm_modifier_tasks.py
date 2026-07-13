"""OpenAI NCCI modifier suggestions for live sessions."""

from __future__ import annotations

import logging
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

MODIFIER_SYSTEM_PROMPT = """You are an expert US NCCI PTP bundling auditor.
Use only the supplied PTP metadata and transcript evidence. Recommend an X modifier
(XE, XS, XP, or XU) only when its distinct-service condition is explicitly supported;
use modifier 59 only when no more specific X modifier applies. Never recommend a
modifier solely to obtain payment. Return only the requested structured JSON."""


class ModifierResponse(BaseModel):
    suggested_modifiers: List[str] = Field(
        default_factory=list,
        description="List of suggested CPT/HCPCS modifiers",
    )
    reasoning: str = Field(
        default="",
        description=(
            "A very short, simple phrase explaining why, "
            "e.g. 'it was performed on a separate anatomical region'"
        ),
    )

    @classmethod
    def model_validate_json(cls, json_data, *args, **kwargs):
        """Pre-process to normalise the LLM's alternate key names before validation."""
        import json as _json

        raw = _json.loads(json_data) if isinstance(json_data, (str, bytes)) else json_data
        if isinstance(raw, dict):
            raw = _normalise_modifier_payload(raw)
        return super().model_validate(raw)


def _normalise_modifier_payload(raw: dict) -> dict:
    """Map common LLM field-name variants to the canonical schema."""
    # Accept 'modifiers' as an alias for 'suggested_modifiers'
    if "modifiers" in raw and "suggested_modifiers" not in raw:
        raw["suggested_modifiers"] = raw.pop("modifiers")

    # If the LLM returned a list of objects like [{"code": "59", ...}], flatten to strings
    mods = raw.get("suggested_modifiers", [])
    if mods and isinstance(mods[0], dict):
        flat: list[str] = []
        reasoning_parts: list[str] = []
        for item in mods:
            code = item.get("code") or item.get("modifier") or ""
            if code:
                flat.append(str(code))
            reason = item.get("reasoning") or item.get("explanation") or ""
            if reason:
                reasoning_parts.append(str(reason))
        raw["suggested_modifiers"] = flat
        if not raw.get("reasoning") and reasoning_parts:
            raw["reasoning"] = "; ".join(reasoning_parts)

    # Ensure reasoning exists
    if "reasoning" not in raw:
        raw["reasoning"] = ""

    return raw


def _modifier_prompt(
    primary_cpt: str,
    bundled_cpt: str,
    transcript: str,
    kb_context: str,
) -> str:
    return f"""Strictly adhere to the knowledge base below.

{kb_context}

Task: An NCCI conflict exists between {primary_cpt} (Primary) and {bundled_cpt} (Bundled). 
Review the transcript to see if they were distinct procedural services, performed on separate body structures, or during separate encounters.

Transcript:
{transcript}

Common Modifiers to use:
- XE: Separate Encounter
- XS: Separate Structure / Organ
- XP: Separate Practitioner
- XU: Unusual Non-Overlapping Service
- 59: Distinct Procedural Service (use only if XE/XS/XP/XU do not apply)

Select the best modifiers to append to the bundled CPT {bundled_cpt} to bypass the bundle conflict. If no modifiers apply, return an empty array.

Return a JSON object with exactly:
- "suggested_modifiers": list of strings (e.g. ["59"] or ["XS"] or [])
- "reasoning": a short, simple phrase explaining why (e.g. "performed on a separate anatomical region")
"""


def _modifier_prompt_threaded(
    primary_cpt: str,
    bundled_cpt: str,
    transcript: str,
    ptp_context: str,
) -> str:
    ptp_block = f"\n{ptp_context}\n" if ptp_context else "\n"
    return f"""{ptp_block}
Task: An NCCI conflict exists between {primary_cpt} (Primary) and {bundled_cpt} (Bundled). 
Review the transcript to see if they were distinct procedural services, performed on separate body structures, or during separate encounters.

Transcript:
{transcript}

Common Modifiers to use:
- XE: Separate Encounter
- XS: Separate Structure / Organ
- XP: Separate Practitioner
- XU: Unusual Non-Overlapping Service
- 59: Distinct Procedural Service (use only if XE/XS/XP/XU do not apply)

Select the best modifiers to append to the bundled CPT {bundled_cpt} to bypass the bundle conflict. If no modifiers apply, return an empty array.

Return a JSON object with exactly:
- "suggested_modifiers": list of strings (e.g. ["59"] or ["XS"] or [])
- "reasoning": a short, simple phrase explaining why (e.g. "performed on a separate anatomical region")
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
                system_prompt=MODIFIER_SYSTEM_PROMPT,
                temperature=0.2,
            )
        logger.info("OpenAI modifier response for %s/%s: %s", primary_cpt, bundled_cpt, result)
        return result
    except Exception as e:
        if is_quota_error(e):
            mark_quota_exhausted(e)
            logger.warning(
                "Modifier suggestion skipped for %s/%s due to rate limit: %s",
                primary_cpt,
                bundled_cpt,
                e,
            )
        else:
            logger.exception("Modifier suggestion failed for %s/%s", primary_cpt, bundled_cpt)
        return {"suggested_modifiers": ["59"], "reasoning": f"Failed to parse AI response: {e}"}
