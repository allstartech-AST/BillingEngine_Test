from app.models.output import Issue

_ADVISORY_MESSAGE_PREFIXES = (
    "billing_detection_summary",
    "Transcript does not strongly support",
    "Detection summary CPT(s)",
    "detected_cpt_codes includes CPT(s) missing from",
    "Session metadata duration unavailable",
    "MUE adjudication indicator",
)


def _is_advisory_issue(issue: Issue) -> bool:
    if issue.severity == "info":
        return True
    if issue.severity != "warning":
        return False
    message = issue.message or ""
    return any(message.startswith(prefix) for prefix in _ADVISORY_MESSAGE_PREFIXES)


def resolve_evaluation_status(
    *,
    active_cpts: set[str],
    detected_cpts: set[str],
    pending_codes: list[str],
    therapist_actions_count: int,
    issues: list[Issue],
) -> str:
    if not active_cpts and detected_cpts:
        return "blocked"

    if pending_codes or therapist_actions_count > 0:
        return "needs_therapist_action"

    if any(issue.severity == "error" for issue in issues):
        return "needs_therapist_action"

    actionable_warnings = [
        issue for issue in issues if issue.severity == "warning" and not _is_advisory_issue(issue)
    ]
    if actionable_warnings:
        return "needs_therapist_action"

    if issues:
        return "ready_with_advisories"

    return "ready"
