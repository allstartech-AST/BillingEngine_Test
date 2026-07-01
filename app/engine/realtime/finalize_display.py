from app.engine.loader import MetadataStore
from app.engine.realtime.ui_display import visible_live_cpt_rows
from app.engine.ui_display import format_duration_mmss, format_session_duration
from app.models.live import FinalizeCptLine, FinalizeDisplay, LiveCptRow, LiveSessionState


def _short_description(cpt_code: str, store: MetadataStore) -> str:
    medexa = store.medexa.get(cpt_code, {})
    label = medexa.get("label")
    if label:
        return str(label)
    desc = store.description(cpt_code)
    if desc:
        return desc.split("—")[0].split("-")[0].strip() or desc
    return cpt_code


def _display_units(row: LiveCptRow) -> int:
    if row.lifecycle != "completed":
        return 0
    if not row.is_timed:
        return 1
    return row.units


def _display_duration(row: LiveCptRow) -> str:
    if row.lifecycle == "completed" and row.duration_minutes_exact > 0:
        return format_duration_mmss(row.duration_minutes_exact)
    if row.lifecycle in ("detected", "manual_billing"):
        return "flat"
    return "—"


def build_finalize_display(state: LiveSessionState, store: MetadataStore) -> FinalizeDisplay:
    rows = visible_live_cpt_rows(state.cpts)
    lines: list[FinalizeCptLine] = []
    total_minutes = 0.0
    billable_units = 0

    rejected_lines: list[FinalizeCptLine] = []

    for row in sorted(state.cpts, key=lambda r: r.sequence):
        units = _display_units(row)
        duration_display = _display_duration(row)
        if row.lifecycle == "completed":
            total_minutes += row.duration_minutes_exact
            billable_units += units
        
        line = FinalizeCptLine(
            cpt_code=row.cpt_code,
            description=_short_description(row.cpt_code, store),
            units=units,
            duration_display=duration_display,
            region="--",
        )
        if row.lifecycle == "removed":
            rejected_lines.append(line)
        elif row.lifecycle not in ("error", "pending_start", "running"):
            lines.append(line)

    return FinalizeDisplay(
        session_time_display=format_session_duration(total_minutes),
        billable_units_total=billable_units,
        cpt_code_count=len(lines),
        total_duration_display=format_session_duration(total_minutes),
        lines=lines,
        rejected_lines=rejected_lines,
    )
