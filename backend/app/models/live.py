from typing import Literal

from pydantic import BaseModel, Field

from app.models.output import BillingConflict, UiDisplay


class LiveClientInfo(BaseModel):
    client_name: str
    client_id: str


class LiveCptRow(BaseModel):
    cpt_code: str
    sequence: int
    lifecycle: Literal[
        "detected",
        "pending_start",
        "running",
        "paused",
        "billing",
        "completed",
        "manual_billing",
        "removed",
        "error",
        "ai_suggested",
    ] = "detected"
    billing_rule: str | None = None
    duration_minutes_exact: float = 0.0
    minutes_billed: int = 0
    units: int = 0
    billing_status: Literal[
        "confirmed",
        "pending_therapist_review",
        "manual",
        "removed",
        "error",
    ] = "confirmed"
    pending_reasons: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    rule_message: str = ""
    icd_guidance: str = ""
    removal_reason: str = ""
    message: str = ""
    applied_modifiers: list[str] = Field(default_factory=list)
    mue_note: str = ""
    ai_supported: bool | None = None
    ai_reasoning: str = ""
    ai_confidence: int | None = None
    region: str = "--"
    area_sq_cm: float = 0.0
    occurrence_count: int = 1


class LiveSessionState(BaseModel):
    session_id: str
    client_info: LiveClientInfo
    icds: list[str] = Field(default_factory=list)
    cpts: list[LiveCptRow] = Field(default_factory=list)
    conflicts: list[BillingConflict] = Field(default_factory=list)
    resolved_conflicts: list[str] = Field(default_factory=list)
    status: Literal["active", "ended", "blocked"] = "active"
    session_message: str = ""
    whole_transcript: str = ""
    billing_rule: Literal["cms_8_minute", "ama_rule_of_8"] = "cms_8_minute"
    last_cpt_suggestion_length: int = 0
    sentences_fed_count: int = 0
    llm_context_ready: bool = False
    llm_turns: list[dict[str, str]] = Field(default_factory=list)


class LiveSessionCreateRequest(BaseModel):
    client_name: str = "Live Demo Patient"
    client_id: str = "LIVE-001"
    billing_rule: Literal["cms_8_minute", "ama_rule_of_8"] = "cms_8_minute"


class LiveIcdRequest(BaseModel):
    icd10_code: str


class LiveCptDetectRequest(BaseModel):
    cpt_code: str


class LiveCptEndRequest(BaseModel):
    cpt_code: str
    duration_minutes: float


class LiveModifierRequest(BaseModel):
    conflict_id: str
    action: Literal["approve", "reject"]
    modifier: str | None = None


class LiveCptDurationRequest(BaseModel):
    cpt_code: str
    duration_minutes: float


class LiveCptAreaRequest(BaseModel):
    cpt_code: str
    area_sq_cm: float

class LiveTranscriptSentenceRequest(BaseModel):
    sentence: str
    sentence_count: int = Field(default=1, ge=1)


class FinalizeCptLine(BaseModel):
    cpt_code: str
    description: str
    units: int
    duration_display: str
    region: str = "--"
    billing_rule: str | None = None
    billing_rule_label: str = "—"
    applied_modifiers: list[str] = Field(default_factory=list)


class FinalizeDisplay(BaseModel):
    session_time_display: str
    billable_units_total: int
    cpt_code_count: int
    total_duration_display: str
    lines: list[FinalizeCptLine] = Field(default_factory=list)
    rejected_lines: list[FinalizeCptLine] = Field(default_factory=list)


class LiveSessionResponse(BaseModel):
    session: LiveSessionState
    ui_display: UiDisplay
    event_message: str = ""
    open_cpt_code: str | None = None
    finalize_display: FinalizeDisplay | None = None
