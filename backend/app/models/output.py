from typing import Any, Literal

from pydantic import BaseModel, Field


class DiagnosisCptResult(BaseModel):
    cpt_code: str
    medical_necessity: Literal[
        "valid",
        "invalid",
        "insufficient_metadata",
        "valid_no_crosswalk",
        "pending_icd_review",
    ]
    matched_icd: str | None = None
    matched_icd_label: str | None = None
    alternative_icds_on_claim: list[str] = Field(default_factory=list)
    valid_icd10_alternatives: list[str] = Field(default_factory=list)
    semantic_confidence: int | None = None
    icd_selection_method: Literal[
        "primary",
        "semantic_ranked",
        "ranked_crosswalk",
        "single_crosswalk",
    ] | None = None
    review_reason: Literal[
        "crosswalk_miss",
        "no_icd_description",
        "low_semantic_match",
    ] | None = None
    guidance: str = ""
    auto_removed: bool = False


class DiagnosisValidation(BaseModel):
    status: Literal["valid", "issues_found", "blocked"]
    primary_icd10: str | None = None
    ranked_icd10_codes: list[str] = Field(default_factory=list)
    submitted_icd10_codes: list[str]
    per_cpt: list[DiagnosisCptResult]


class BillableCode(BaseModel):
    cpt_code: str
    description: str
    duration_minutes: float
    duration_minutes_exact: float | None = None
    duration_minutes_billed: int | None = None
    units: int
    unit_calculation_method: Literal["eight_minute_rule", "occurrence"]
    is_timed: bool
    sequences: list[int] = Field(default_factory=list)
    billing_status: Literal["confirmed", "pending_therapist_review"] = "confirmed"
    pending_reasons: list[str] = Field(default_factory=list)
    units_status_message: str = ""
    pending_conflict_ids: list[str] = Field(default_factory=list)


class RemovedCode(BaseModel):
    cpt_code: str
    reason: str
    details: str
    auto_applied: bool = True


class TherapistAction(BaseModel):
    type: str
    codes: list[str]
    modifier_indicator: str
    modifiers_suggested: list[str]
    modifiers_not_applicable: list[str]
    guidance: str
    conflict_id: str | None = None


class ConflictRecommendation(BaseModel):
    action: str
    summary: str
    modifiers: list[str] = Field(default_factory=list)


class BillingConflict(BaseModel):
    conflict_id: str
    conflict_type: Literal["bypassable_bundle", "transcript_weak", "overlap"]
    codes: list[str]
    column_one_code: str | None = None
    column_two_code: str | None = None
    column_one_description: str | None = None
    column_two_description: str | None = None
    modifier_applies_to: str | None = None
    issue: str
    recommendations: list[ConflictRecommendation]
    modifier_indicator: str | None = None
    ai_enriched: bool = False


class TranscriptCptSupport(BaseModel):
    cpt_code: str
    transcript_support: Literal[
        "supported", "weak", "suppressed", "not_applicable", "no_lookup"
    ]
    confidence_score: int | None = None
    matched_phrases: list[str] = Field(default_factory=list)
    matched_context: list[str] = Field(default_factory=list)
    suppressed_by: str | None = None
    guidance: str = ""


class TranscriptIcdSupport(BaseModel):
    icd10_code: str
    label: str | None = None
    transcript_support: Literal["supported", "weak", "suppressed", "no_lookup"]
    confidence_score: int | None = None
    matched_phrases: list[str] = Field(default_factory=list)
    matched_context: list[str] = Field(default_factory=list)
    suppressed_by: str | None = None
    guidance: str = ""


class TranscriptIcdValidation(BaseModel):
    status: Literal["complete", "partial", "skipped"]
    per_icd: list[TranscriptIcdSupport]


class TranscriptValidation(BaseModel):
    cpt_support: list[TranscriptCptSupport]
    icd_validation: TranscriptIcdValidation


class Issue(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str | None = None
    message: str


class AutoAppliedChange(BaseModel):
    action: str
    cpt_code: str
    details: str


class SessionSummary(BaseModel):
    total_session_duration_minutes: float
    total_timed_minutes: float
    total_timeline_minutes: float = 0.0
    evaluation_status: Literal[
        "ready",
        "ready_with_advisories",
        "needs_therapist_action",
        "blocked",
    ]


class SegmentOverlap(BaseModel):
    sequence: int
    cpt_code: str
    overlap_type: Literal["identical", "partial"]


class SegmentReview(BaseModel):
    sequence: int
    cpt_code: str
    timestamp_start: str
    timestamp_end: str
    duration_minutes_exact: float
    duration_minutes_billed: int
    overlaps_with: list[SegmentOverlap] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    billing_status: Literal["confirmed", "pending_therapist_review", "removed"]
    pending_reasons: list[str] = Field(default_factory=list)


class ConflictGroup(BaseModel):
    group_id: str
    group_type: Literal["temporal_overlap", "ncci_hub", "ncci_pair", "other"]
    anchor_cpt: str | None = None
    priority: int
    conflict_ids: list[str] = Field(default_factory=list)
    summary: str


class HumanSummaryDiagnosis(BaseModel):
    icd10_code: str
    description: str | None = None
    transcript_support: str
    confidence_score: int | None = None
    guidance: str = ""


class HumanSummaryCpt(BaseModel):
    cpt_code: str
    description: str
    transcript_support: str
    confidence_score: int | None = None
    duration_minutes: float
    units: int | None = None
    billing_status: Literal["confirmed", "pending_therapist_review", "removed"]
    units_status_message: str = ""
    guidance: str = ""


class HumanSummary(BaseModel):
    patient_name: str
    patient_id: str
    overall_status: Literal[
        "ready",
        "ready_with_advisories",
        "needs_therapist_action",
        "blocked",
    ]
    diagnoses: list[HumanSummaryDiagnosis]
    cpt_codes: list[HumanSummaryCpt]
    confirmed_billable: list[str]
    pending_authorization: list[str]
    conflicts: list[BillingConflict]
    conflict_groups: list[ConflictGroup] = Field(default_factory=list)
    segment_review: list[SegmentReview] = Field(default_factory=list)
    removed_automatically: list[dict[str, Any]]
    session_timing: dict[str, Any]
    units_breakdown: dict[str, Any]
    narrative: str


class UiProvisionalUnits(BaseModel):
    max: int
    conservative: int


class UiSuggestion(BaseModel):
    type: str
    severity: Literal["action_required", "advisory"]
    summary: str
    conflict_id: str | None = None
    modifiers: list[str] = Field(default_factory=list)


class UiCptActions(BaseModel):
    reject_enabled: bool = False
    approve_enabled: bool = False


class UiCptCard(BaseModel):
    cpt_code: str
    short_label: str
    description: str
    units_display: int
    units_current: int
    duration_display: str
    duration_minutes_exact: float
    verification_status: Literal["confirmed", "pending_review"]
    card_style: Literal["standard", "review"]
    badge: str | None = None
    conflict_message: str | None = None
    conflict_with_cpt: str | None = None
    conflict_id: str | None = None
    modifiers_suggested: list[str] = Field(default_factory=list)
    actions: UiCptActions = Field(default_factory=UiCptActions)
    provisional_units: UiProvisionalUnits | None = None
    suggestions: list[UiSuggestion] = Field(default_factory=list)
    sequences: list[int] = Field(default_factory=list)
    is_timed: bool = True
    applied_modifiers: list[str] = Field(default_factory=list)
    is_addon: bool = False
    parent_cpt_code: str | None = None


class UiIcdSuggestion(BaseModel):
    type: str
    severity: Literal["action_required", "advisory"]
    summary: str


class UiIcdCard(BaseModel):
    icd10_code: str
    detected_icd10_codes: list[str] = Field(default_factory=list)
    label: str | None = None
    is_primary: bool = False
    transcript_support: str
    confidence_score: int | None = None
    linked_cpt_codes: list[str] = Field(default_factory=list)
    crosswalk_summary: str = ""
    verification_status: Literal["confirmed", "pending_review"]
    card_style: Literal["standard", "review"]
    suggestions: list[UiIcdSuggestion] = Field(default_factory=list)
    acknowledge_enabled: bool = False


class UiRemovedCard(BaseModel):
    cpt_code: str
    reason: str
    details: str
    auto_applied: bool = True


class UiSessionHeader(BaseModel):
    session_title: str
    status_label: str
    session_datetime: str
    patient_id: str
    patient_name: str
    duration_display: str
    units_total: int


class UiSummaryCards(BaseModel):
    session_time_display: str
    session_units_total: int
    eight_minute_rule: bool
    billing_rule: str = "cms_8_minute"
    threshold_note: str = ""


class UiDisplay(BaseModel):
    session_header: UiSessionHeader
    summary_cards: UiSummaryCards
    icd_cards: list[UiIcdCard] = Field(default_factory=list)
    cpt_cards: list[UiCptCard] = Field(default_factory=list)
    removed_section: list[UiRemovedCard] = Field(default_factory=list)


class BillingReport(BaseModel):
    client_info: dict
    diagnosis_validation: DiagnosisValidation
    session_summary: SessionSummary
    billable_codes: list[BillableCode]
    confirmed_billable_codes: list[str] = Field(default_factory=list)
    pending_authorization_codes: list[str] = Field(default_factory=list)
    removed_codes: list[RemovedCode]
    therapist_actions_required: list[TherapistAction]
    billing_conflicts: list[BillingConflict] = Field(default_factory=list)
    conflict_groups: list[ConflictGroup] = Field(default_factory=list)
    segment_review: list[SegmentReview] = Field(default_factory=list)
    transcript_validation: TranscriptValidation
    human_summary: HumanSummary
    ui_display: UiDisplay
    issues: list[Issue]
    auto_applied_changes: list[AutoAppliedChange]
