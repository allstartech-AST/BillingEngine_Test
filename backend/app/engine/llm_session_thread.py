"""One OpenAI conversation thread per live session — reference data sent once."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel

from app.engine.llm_kb import build_compact_medexa_reference, build_compact_ptp_pair_context
from app.engine.llm_provider import generate_json_pydantic_messages, is_configured
from app.engine.loader import MetadataStore
from app.models.live import LiveSessionState

logger = logging.getLogger(__name__)

_SESSION_SYSTEM = (
    "You are an expert medical billing AI for outpatient PT/OT/SLP live therapy sessions."
)


def _bootstrap_turns(store: MetadataStore) -> list[dict[str, str]]:
    reference = build_compact_medexa_reference(store)
    return [
        {
            "role": "user",
            "content": (
                "Session reference — use only CPT codes from this Medexa dictionary for "
                "all verify, missing-code, and modifier tasks in this visit:\n\n"
                f"{reference}\n\n"
                "I will send transcript segments and specific tasks next."
            ),
        },
        {
            "role": "assistant",
            "content": (
                "Understood. I will use only codes from the Medexa dictionary and apply "
                "clinical reasoning to each transcript segment you provide."
            ),
        },
    ]


class LiveEnrichmentThread:
    """Per-session message history for live enrichment LLM calls."""

    def __init__(self, state: LiveSessionState, store: MetadataStore) -> None:
        self.state = state
        self.store = store

    def _messages_for_call(self, user_prompt: str) -> list[dict[str, str]]:
        turns: list[dict[str, str]] = [{"role": "system", "content": _SESSION_SYSTEM}]
        if not self.state.llm_context_ready:
            turns.extend(_bootstrap_turns(self.store))
        else:
            turns.extend(self.state.llm_turns)
        turns.append({"role": "user", "content": user_prompt})
        return turns

    async def complete_json(
        self,
        user_prompt: str,
        response_model: type[BaseModel],
        *,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        if not is_configured():
            raise ValueError("OpenAI API key is not configured.")

        messages = self._messages_for_call(user_prompt)
        result = await generate_json_pydantic_messages(
            messages=messages,
            response_model=response_model,
            temperature=temperature,
        )

        if not self.state.llm_context_ready:
            self.state.llm_context_ready = True
            self.state.llm_turns = _bootstrap_turns(self.store)

        self.state.llm_turns.append({"role": "user", "content": user_prompt})
        self.state.llm_turns.append(
            {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)}
        )
        logger.info(
            "Live LLM thread %s: turn recorded (%s turns stored)",
            self.state.session_id,
            len(self.state.llm_turns),
        )
        return result

    def compact_ptp_pair(self, primary_cpt: str, bundled_cpt: str) -> str:
        return build_compact_ptp_pair_context(self.store, primary_cpt, bundled_cpt)
