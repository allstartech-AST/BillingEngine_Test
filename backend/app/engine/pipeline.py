import re

from app.engine.conflict_groups import group_billing_conflicts
from app.engine.conflicts import filter_billing_conflicts, filter_therapist_actions
from app.engine.evaluation_status import resolve_evaluation_status
from app.engine.pending_review import REVIEW_REASON_LABELS, build_pending_review
from app.engine.aoc import validate_addon_codes
from app.engine.detection_summary import reconcile_detection_summary
from app.engine.duration import (
    merged_timeline_minutes,
    segment_duration_details,
    session_duration_minutes,
)
from app.engine.billing_dispatcher import calculate_all_units
from app.engine.eight_minute import EIGHT_MINUTE_RULE
from app.engine.human_summary import build_human_summary
from app.engine.icd10 import (
    extract_icd_codes,
    extract_icd_codes_ranked,
    resolve_primary_icd,
    validate_medical_necessity,
    _looks_like_icd10,
)
from app.engine.loader import MetadataStore
from app.engine.mue import apply_mue_cap, check_mue_zero
from app.engine.ptp import resolve_ptp_conflicts
from app.engine.segment_review import build_segment_review, overlap_pending_sequences
from app.engine.temporal_overlap import check_temporal_overlaps
from app.engine.ui_display import build_ui_display
from app.engine.transcript_medexa import (
    icd_validation_status,
    validate_all_icd_transcript_support,
    validate_all_transcript_support,
)
from app.models.input import BillingSessionInput
from app.models.output import (
    AutoAppliedChange,
    BillableCode,
    BillingReport,
    DiagnosisValidation,
    Issue,
    RemovedCode,
    SessionSummary,
    TranscriptIcdValidation,
    TranscriptValidation,
)

_PLACEHOLDER_ICD_KEY = re.compile(r"^icd[_-]?\d+$", re.I)


def _diagnosis_labels(diagnoses: dict[str, str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for key, value in diagnoses.items():
        key = (key or "").strip()
        value = (value or "").strip()
        if _looks_like_icd10(key) and value and not _looks_like_icd10(value):
            labels[key] = value
        if _looks_like_icd10(value) and key and not _looks_like_icd10(key):
            if not _PLACEHOLDER_ICD_KEY.match(key):
                labels[value] = key
    return labels


def _pending_cpts_from_conflicts(billing_conflicts) -> set[str]:
    pending: set[str] = set()
    for conflict in billing_conflicts:
        if conflict.conflict_type == "bypassable_bundle":
            pending.update(conflict.codes)
    return pending


def _conflict_ids_for_cpt(cpt: str, billing_conflicts) -> list[str]:
    return [c.conflict_id for c in billing_conflicts if cpt in c.codes]


def _overlap_cpts(conflicts) -> set[str]:
    overlap: set[str] = set()
    for c in conflicts:
        if c.conflict_type == "overlap":
            overlap.update(c.codes)
    return overlap


def evaluate_session(payload: BillingSessionInput, store: MetadataStore) -> BillingReport:
    issues: list[Issue] = []
    removed_records: list[RemovedCode] = []
    auto_changes: list[AutoAppliedChange] = []
    therapist_actions: list = []
    billing_conflicts: list = []

    submitted_icds = extract_icd_codes(payload.diagnoses)
    ranked_icds = extract_icd_codes_ranked(payload.diagnoses)
    resolved_primary = resolve_primary_icd(ranked_icds, payload.primary_icd10)
    diagnosis_labels = _diagnosis_labels(payload.diagnoses)
    detected_cpts = {item.cpt_code for item in payload.detected_cpt_codes}

    issues.extend(
        reconcile_detection_summary(
            payload.billing_detection_summary,
            detected_cpts,
            payload.whole_transcript,
            store,
        )
    )

    segments_by_cpt: dict[str, dict] = {}
    for item in payload.detected_cpt_codes:
        try:
            exact, billed = segment_duration_details(item.timestamp_start, item.timestamp_end)
        except ValueError:
            exact, billed = 0.0, 0
            issues.append(
                Issue(
                    severity="warning",
                    code=item.cpt_code,
                    message=f"Invalid timestamps for {item.cpt_code}.",
                )
            )
        bucket = segments_by_cpt.setdefault(
            item.cpt_code,
            {"minutes_exact": 0.0, "minutes_billed": 0, "minutes": 0.0, "sequences": []},
        )
        bucket["minutes_exact"] += exact
        bucket["minutes_billed"] += billed
        bucket["minutes"] = bucket["minutes_exact"]
        bucket["sequences"].append(item.sequence)

    overlap_issues, overlap_conflicts = check_temporal_overlaps(payload.detected_cpt_codes)
    issues.extend(overlap_issues)
    billing_conflicts.extend(overlap_conflicts)

    unknown = {c for c in detected_cpts if not store.knows_cpt(c)}
    active = detected_cpts - unknown
    for cpt in sorted(unknown):
        detail = f"CPT {cpt} not found in billing metadata files."
        removed_records.append(
            RemovedCode(cpt_code=cpt, reason="unknown_code", details=detail, auto_applied=True)
        )
        auto_changes.append(
            AutoAppliedChange(action="remove_unknown", cpt_code=cpt, details=detail)
        )
        issues.append(Issue(severity="error", code=cpt, message=detail))

    diagnosis_results, icd_pending_cpts = validate_medical_necessity(
        active,
        ranked_icds,
        store,
        diagnosis_labels=diagnosis_labels,
        primary_icd=payload.primary_icd10,
    )
    diagnosis_by_cpt = {r.cpt_code: r for r in diagnosis_results}
    for result in diagnosis_results:
        if result.medical_necessity == "pending_icd_review":
            issues.append(
                Issue(
                    severity="warning",
                    code=result.cpt_code,
                    message=result.guidance or (
                        f"ICD medical necessity for {result.cpt_code} requires therapist review."
                    ),
                )
            )

    addon_removed, addon_removed_records, addon_changes, addon_issues = validate_addon_codes(
        active, store
    )
    active -= addon_removed
    removed_records.extend(addon_removed_records)
    auto_changes.extend(addon_changes)
    issues.extend(addon_issues)

    ptp_removed, ptp_removed_records, ptp_actions, ptp_changes, ptp_conflicts = resolve_ptp_conflicts(
        active, store
    )
    billing_conflicts.extend(ptp_conflicts)
    active -= ptp_removed
    removed_records.extend(ptp_removed_records)
    auto_changes.extend(ptp_changes)
    therapist_actions.extend(ptp_actions)

    mue_zero_removed, mue_zero_records, mue_zero_changes, mue_issues = check_mue_zero(
        active, store
    )
    active -= mue_zero_removed
    removed_records.extend(mue_zero_records)
    auto_changes.extend(mue_zero_changes)
    issues.extend(mue_issues)

    billing_conflicts = filter_billing_conflicts(billing_conflicts, active)
    therapist_actions = filter_therapist_actions(therapist_actions, billing_conflicts)

    ncci_pending_cpts = _pending_cpts_from_conflicts(billing_conflicts)
    overlap_cpts = _overlap_cpts(billing_conflicts)
    pending_cpts = ncci_pending_cpts | (icd_pending_cpts & active) | (overlap_cpts & active)

    active_segs = {cpt: segments_by_cpt[cpt] for cpt in active if cpt in segments_by_cpt}
    unit_results = calculate_all_units(active_segs, store, payload.billing_rule)

    billable: list[BillableCode] = []
    for item in unit_results:
        before = item.units
        after, _limit = apply_mue_cap(item.cpt_code, before, store)
        if after < before:
            detail = f"Units capped from {before} to {after} by MUE for {item.cpt_code}."
            auto_changes.append(
                AutoAppliedChange(
                    action="cap_mue",
                    cpt_code=item.cpt_code,
                    details=detail,
                )
            )
            issues.append(Issue(severity="info", code=item.cpt_code, message=detail))

        is_pending = item.cpt_code in pending_cpts
        icd_pending = item.cpt_code in icd_pending_cpts
        ncci_pending = item.cpt_code in ncci_pending_cpts
        overlap_pending = item.cpt_code in overlap_cpts
        conflict_ids = _conflict_ids_for_cpt(item.cpt_code, billing_conflicts)
        pending_reasons, status_message = build_pending_review(
            item.cpt_code,
            icd_pending=icd_pending,
            ncci_pending=ncci_pending,
            overlap_pending=overlap_pending,
            diagnosis=diagnosis_by_cpt.get(item.cpt_code),
        )
        billable.append(
            BillableCode(
                cpt_code=item.cpt_code,
                description=store.description(item.cpt_code),
                duration_minutes=float(item.minutes_billed),
                duration_minutes_exact=round(item.minutes_exact, 2),
                duration_minutes_billed=item.minutes_billed,
                units=after,
                unit_calculation_method=item.method,
                billing_rule=store.billing_rule(item.cpt_code),
                sequences=item.sequences,
                billing_status="pending_therapist_review" if is_pending else "confirmed",
                pending_reasons=pending_reasons,
                units_status_message=status_message if is_pending else "",
                pending_conflict_ids=conflict_ids,
            )
        )

    transcript_support = validate_all_transcript_support(
        sorted(detected_cpts),
        payload.whole_transcript,
        store,
    )
    for support in transcript_support:
        if support.transcript_support == "weak" and support.cpt_code in active:
            issues.append(
                Issue(
                    severity="warning",
                    code=support.cpt_code,
                    message=(
                        f"Transcript does not strongly support billed CPT {support.cpt_code}."
                    ),
                )
            )

    icd_support = validate_all_icd_transcript_support(
        submitted_icds,
        payload.whole_transcript,
        store,
        diagnosis_labels=diagnosis_labels,
    )
    for icd_result in icd_support:
        if icd_result.transcript_support == "weak":
            issues.append(
                Issue(
                    severity="warning",
                    code=icd_result.icd10_code,
                    message=(
                        f"Transcript does not strongly support submitted ICD-10 "
                        f"{icd_result.icd10_code}."
                    ),
                )
            )

    icd_val = TranscriptIcdValidation(
        status=icd_validation_status(icd_support, payload.whole_transcript),  # type: ignore[arg-type]
        per_icd=icd_support,
    )

    session_mins = session_duration_minutes(
        payload.session_metadata.session_start,
        payload.session_metadata.session_end,
    )
    if session_mins <= 0:
        session_mins = round(
            sum(s.get("minutes_exact", s.get("minutes", 0.0)) for s in segments_by_cpt.values()),
            2,
        )
        issues.append(
            Issue(
                severity="info",
                message="Session metadata duration unavailable; used sum of segment durations.",
            )
        )

    total_timed = round(
        sum(
            segments_by_cpt[c].get("minutes_billed", 0)
            for c in active
            if store.billing_rule(c) == EIGHT_MINUTE_RULE and c in segments_by_cpt
        ),
        2,
    )
    total_timeline = merged_timeline_minutes(
        [(item.timestamp_start, item.timestamp_end) for item in payload.detected_cpt_codes]
    )

    confirmed_codes = [c.cpt_code for c in billable if c.billing_status == "confirmed"]
    pending_codes = [c.cpt_code for c in billable if c.billing_status == "pending_therapist_review"]
    removed_cpts = {r.cpt_code for r in removed_records}

    eval_status = resolve_evaluation_status(
        active_cpts=active,
        detected_cpts=detected_cpts,
        pending_codes=pending_codes,
        therapist_actions_count=len(therapist_actions),
        issues=issues,
    )

    pending_icd_count = sum(
        1 for r in diagnosis_results if r.medical_necessity == "pending_icd_review"
    )
    if pending_icd_count:
        diag_status = "issues_found"
    elif not active and detected_cpts:
        diag_status = "blocked"
    else:
        diag_status = "valid"

    conflict_groups = group_billing_conflicts(billing_conflicts)
    overlap_sequences = overlap_pending_sequences(billing_conflicts, active)
    segment_review = build_segment_review(
        payload.detected_cpt_codes,
        billing_conflicts,
        active_cpts=active,
        removed_cpts=removed_cpts,
        overlap_sequences=overlap_sequences,
        ncci_pending_cpts=ncci_pending_cpts,
        icd_pending_cpts=icd_pending_cpts,
    )

    human_summary = build_human_summary(
        payload,
        store,
        eval_status=eval_status,
        submitted_icds=submitted_icds,
        ranked_icds=ranked_icds,
        resolved_primary=resolved_primary,
        icd_support=icd_support,
        cpt_support=transcript_support,
        billable_codes=billable,
        removed_codes=removed_records,
        billing_conflicts=billing_conflicts,
        conflict_groups=conflict_groups,
        segment_review=segment_review,
        session_mins=session_mins,
        total_timed=total_timed,
        total_timeline=total_timeline,
        segments_by_cpt=segments_by_cpt,
        detected_cpts=detected_cpts,
        diagnosis_results=diagnosis_results,
    )

    ui_display = build_ui_display(
        payload,
        store,
        eval_status=eval_status,
        billable_codes=billable,
        removed_codes=removed_records,
        billing_conflicts=billing_conflicts,
        segments_by_cpt=segments_by_cpt,
        active_cpts=active,
        detected_cpts=detected_cpts,
        diagnosis_results=diagnosis_results,
        icd_support=icd_support,
        cpt_support=transcript_support,
        resolved_primary=resolved_primary,
        ranked_icds=ranked_icds,
        total_timeline_minutes=total_timeline,
        ncci_pending_cpts=ncci_pending_cpts,
        icd_pending_cpts=icd_pending_cpts,
    )

    return BillingReport(
        client_info=payload.client_info.model_dump(),
        diagnosis_validation=DiagnosisValidation(
            status=diag_status,
            primary_icd10=resolved_primary,
            ranked_icd10_codes=ranked_icds,
            submitted_icd10_codes=submitted_icds,
            per_cpt=diagnosis_results,
        ),
        session_summary=SessionSummary(
            total_session_duration_minutes=session_mins,
            total_timed_minutes=total_timed,
            total_timeline_minutes=total_timeline,
            evaluation_status=eval_status,
        ),
        billable_codes=sorted(billable, key=lambda x: min(x.sequences) if x.sequences else 0),
        confirmed_billable_codes=confirmed_codes,
        pending_authorization_codes=pending_codes,
        removed_codes=removed_records,
        therapist_actions_required=therapist_actions,
        billing_conflicts=billing_conflicts,
        conflict_groups=conflict_groups,
        segment_review=segment_review,
        transcript_validation=TranscriptValidation(
            cpt_support=transcript_support,
            icd_validation=icd_val,
        ),
        human_summary=human_summary,
        ui_display=ui_display,
        issues=issues,
        auto_applied_changes=auto_changes,
    )
