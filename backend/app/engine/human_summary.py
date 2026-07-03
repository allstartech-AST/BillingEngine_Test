from app.config import PENDING_UNITS_MESSAGE
from app.engine.loader import MetadataStore
from app.engine.pending_review import PENDING_REASON_LABELS, REVIEW_REASON_LABELS
from app.models.input import BillingSessionInput
from app.models.output import (
    BillableCode,
    BillingConflict,
    ConflictGroup,
    DiagnosisCptResult,
    HumanSummary,
    HumanSummaryCpt,
    HumanSummaryDiagnosis,
    RemovedCode,
    SegmentReview,
    TranscriptCptSupport,
    TranscriptIcdSupport,
)


def _confidence_label(score: int | None) -> str:
    if score is None:
        return "not scored"
    if score >= 70:
        return "strong"
    if score >= 40:
        return "moderate"
    return "weak"


def build_human_summary(
    payload: BillingSessionInput,
    store: MetadataStore,
    *,
    eval_status: str,
    submitted_icds: list[str],
    ranked_icds: list[str] | None = None,
    resolved_primary: str | None = None,
    icd_support: list[TranscriptIcdSupport],
    cpt_support: list[TranscriptCptSupport],
    billable_codes: list[BillableCode],
    removed_codes: list[RemovedCode],
    billing_conflicts: list[BillingConflict],
    conflict_groups: list[ConflictGroup] | None = None,
    segment_review: list[SegmentReview] | None = None,
    session_mins: float,
    total_timed: float,
    total_timeline: float = 0.0,
    segments_by_cpt: dict[str, dict],
    detected_cpts: set[str],
    diagnosis_results: list[DiagnosisCptResult] | None = None,
) -> HumanSummary:
    support_by_cpt = {s.cpt_code: s for s in cpt_support}
    confirmed = [c.cpt_code for c in billable_codes if c.billing_status == "confirmed"]
    pending = [c.cpt_code for c in billable_codes if c.billing_status == "pending_therapist_review"]

    diagnoses: list[HumanSummaryDiagnosis] = []
    for icd in submitted_icds:
        match = next((r for r in icd_support if r.icd10_code == icd), None)
        if match:
            diagnoses.append(
                HumanSummaryDiagnosis(
                    icd10_code=icd,
                    description=match.label,
                    transcript_support=match.transcript_support,
                    confidence_score=match.confidence_score,
                    guidance=match.guidance,
                )
            )
        else:
            diagnoses.append(
                HumanSummaryDiagnosis(
                    icd10_code=icd,
                    transcript_support="no_lookup",
                    guidance="No transcript validation result available.",
                )
            )

    cpt_rows: list[HumanSummaryCpt] = []
    billable_by_cpt = {c.cpt_code: c for c in billable_codes}
    removed_set = {r.cpt_code for r in removed_codes}

    for cpt in sorted(detected_cpts):
        support = support_by_cpt.get(cpt)
        seg = segments_by_cpt.get(cpt, {"minutes": 0.0, "sequences": []})
        if cpt in removed_set:
            cpt_rows.append(
                HumanSummaryCpt(
                    cpt_code=cpt,
                    description=store.description(cpt),
                    transcript_support=support.transcript_support if support else "no_lookup",
                    confidence_score=support.confidence_score if support else None,
                    duration_minutes=round(seg.get("minutes", 0.0), 2),
                    units=None,
                    billing_status="removed",
                    guidance=support.guidance if support else "Removed by billing rules.",
                )
            )
            continue

        billable = billable_by_cpt.get(cpt)
        if billable:
            cpt_rows.append(
                HumanSummaryCpt(
                    cpt_code=cpt,
                    description=billable.description,
                    transcript_support=support.transcript_support if support else "no_lookup",
                    confidence_score=support.confidence_score if support else None,
                    duration_minutes=billable.duration_minutes,
                    units=billable.units,
                    billing_status=billable.billing_status,
                    units_status_message=billable.units_status_message,
                    guidance=support.guidance if support else "",
                )
            )

    confirmed_units = sum(c.units for c in billable_codes if c.billing_status == "confirmed")
    pending_units = sum(c.units for c in billable_codes if c.billing_status == "pending_therapist_review")

    per_code_timing = {
        cpt: {
            "duration_minutes": round(segments_by_cpt.get(cpt, {}).get("minutes", 0.0), 2),
            "sequences": segments_by_cpt.get(cpt, {}).get("sequences", []),
        }
        for cpt in sorted(detected_cpts)
    }

    units_breakdown = {
        "confirmed_units": confirmed_units,
        "pending_units": pending_units,
        "total_calculated_units": confirmed_units + pending_units,
        "confirmed_codes": confirmed,
        "pending_codes": pending,
        "pending_units_message": PENDING_UNITS_MESSAGE,
    }

    removed_auto = [
        {
            "cpt_code": r.cpt_code,
            "reason": r.reason,
            "details": r.details,
            "certainty": "100%",
        }
        for r in removed_codes
        if r.auto_applied
    ]

    session_timing = {
        "total_session_duration_minutes": session_mins,
        "total_timed_minutes": total_timed,
        "total_timeline_minutes": total_timeline,
        "primary_icd10": resolved_primary,
        "ranked_icd10_codes": ranked_icds or submitted_icds,
        "per_code": per_code_timing,
    }

    narrative = _render_narrative(
        payload=payload,
        eval_status=eval_status,
        diagnoses=diagnoses,
        cpt_rows=cpt_rows,
        confirmed=confirmed,
        pending=pending,
        billing_conflicts=billing_conflicts,
        removed_auto=removed_auto,
        session_timing=session_timing,
        units_breakdown=units_breakdown,
        billable_codes=billable_codes,
    )

    return HumanSummary(
        patient_name=payload.client_info.client_name,
        patient_id=payload.client_info.client_id,
        overall_status=eval_status,  # type: ignore[arg-type]
        diagnoses=diagnoses,
        cpt_codes=cpt_rows,
        confirmed_billable=confirmed,
        pending_authorization=pending,
        conflicts=billing_conflicts,
        conflict_groups=conflict_groups or [],
        segment_review=segment_review or [],
        removed_automatically=removed_auto,
        session_timing=session_timing,
        units_breakdown=units_breakdown,
        narrative=narrative,
    )


def _render_narrative(
    *,
    payload: BillingSessionInput,
    eval_status: str,
    diagnoses: list[HumanSummaryDiagnosis],
    cpt_rows: list[HumanSummaryCpt],
    confirmed: list[str],
    pending: list[str],
    billing_conflicts: list[BillingConflict],
    removed_auto: list[dict],
    session_timing: dict,
    units_breakdown: dict,
    billable_codes: list[BillableCode],
) -> str:
    lines: list[str] = []
    lines.append("BILLING EVALUATION SUMMARY")
    lines.append("=" * 40)
    lines.append("")
    lines.append("PATIENT")
    lines.append(f"  Name: {payload.client_info.client_name}")
    lines.append(f"  ID:   {payload.client_info.client_id}")
    lines.append(f"  Status: {eval_status.replace('_', ' ')}")
    lines.append("")

    lines.append("DIAGNOSES (ICD-10)")
    for d in diagnoses:
        score = f"{d.confidence_score}/100" if d.confidence_score is not None else "N/A"
        label = f" — {d.description}" if d.description else ""
        lines.append(
            f"  {d.icd10_code}{label}: transcript {_confidence_label(d.confidence_score)} "
            f"(confidence {score}, support={d.transcript_support})"
        )
        if d.guidance:
            lines.append(f"    Note: {d.guidance}")
    lines.append("")

    lines.append("SERVICES DETECTED (CPT)")
    for c in cpt_rows:
        score = f"{c.confidence_score}/100" if c.confidence_score is not None else "N/A"
        lines.append(
            f"  {c.cpt_code}: {c.duration_minutes} min, "
            f"transcript {_confidence_label(c.confidence_score)} (confidence {score})"
        )
    lines.append("")

    lines.append("CONFIRMED BILLABLE (system certain)")
    if confirmed:
        for code in confirmed:
            row = next((c for c in billable_codes if c.cpt_code == code), None)
            units = row.units if row else "?"
            lines.append(f"  {code} — {units} unit(s)")
    else:
        lines.append("  None")
    lines.append("")

    lines.append("AWAITING THERAPIST AUTHORIZATION")
    if pending:
        for code in pending:
            row = next((c for c in billable_codes if c.cpt_code == code), None)
            units = row.units if row else "?"
            lines.append(f"  {code} — {units} provisional unit(s)")
            if row and row.units_status_message:
                lines.append(f"    {row.units_status_message}")
    else:
        lines.append("  None")
    lines.append("")

    if billing_conflicts:
        lines.append("CONFLICTS AND RECOMMENDATIONS")
        for conflict in billing_conflicts:
            lines.append(f"  [{conflict.conflict_id}] {conflict.issue}")
            for i, rec in enumerate(conflict.recommendations, 1):
                lines.append(f"    {i}. {rec.summary}")
        lines.append("")

    if removed_auto:
        lines.append("REMOVED AUTOMATICALLY (100% certain)")
        for item in removed_auto:
            lines.append(f"  {item['cpt_code']}: {item['details']}")
        lines.append("")

    lines.append("SESSION AND UNITS")
    lines.append(
        f"  Total session: {session_timing['total_session_duration_minutes']} min | "
        f"Timed treatment: {session_timing['total_timed_minutes']} min | "
        f"Timeline (merged): {session_timing.get('total_timeline_minutes', 0)} min"
    )
    lines.append(
        f"  Confirmed units: {units_breakdown['confirmed_units']} | "
        f"Pending units: {units_breakdown['pending_units']}"
    )
    for c in billable_codes:
        status_note = ""
        if c.billing_status == "pending_therapist_review":
            status_note = f" — {PENDING_UNITS_MESSAGE}"
        lines.append(
            f"  {c.cpt_code}: {c.duration_minutes} min -> {c.units} unit(s)"
            f" [{c.billing_status}]{status_note}"
        )

    return "\n".join(lines)
