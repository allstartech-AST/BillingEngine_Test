from datetime import datetime


def _parse_instant(value: str) -> datetime | None:
    value = value.strip()
    if "T" not in value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_timestamp(value: str) -> int:
    """Parse HH:MM:SS to total seconds."""
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp: {value}")
    hours, minutes, seconds = (int(p) for p in parts)
    return hours * 3600 + minutes * 60 + seconds


def segment_duration_seconds(start: str, end: str) -> float:
    start_dt = _parse_instant(start)
    end_dt = _parse_instant(end)
    if start_dt and end_dt:
        delta = (end_dt - start_dt).total_seconds()
        if delta < 0:
            delta += 24 * 3600
        return delta

    start_s = parse_timestamp(start)
    end_s = parse_timestamp(end)
    if end_s < start_s:
        end_s += 24 * 3600
    return float(end_s - start_s)


def round_minutes_for_billing(total_seconds: float) -> int:
    """Round duration to whole minutes: >=30s up, <=29s down."""
    whole_seconds = int(round(total_seconds))
    whole_minutes = whole_seconds // 60
    remainder = whole_seconds % 60
    if remainder >= 30:
        whole_minutes += 1
    return whole_minutes


def segment_duration_details(start: str, end: str) -> tuple[float, int]:
    """Return (exact_minutes, billed_whole_minutes)."""
    seconds = segment_duration_seconds(start, end)
    exact = round(seconds / 60.0, 2)
    billed = round_minutes_for_billing(seconds)
    return exact, billed


def segment_duration_minutes(start: str, end: str) -> float:
    """Backward-compatible: returns exact fractional minutes."""
    exact, _ = segment_duration_details(start, end)
    return exact


def session_duration_minutes(session_start: str, session_end: str) -> float:
    try:
        start = datetime.fromisoformat(session_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(session_end.replace("Z", "+00:00"))
        return round((end - start).total_seconds() / 60.0, 2)
    except ValueError:
        return 0.0


def _segment_interval_seconds(start: str, end: str) -> tuple[int, int]:
    start_dt = _parse_instant(start)
    end_dt = _parse_instant(end)
    if start_dt and end_dt:
        a0 = int(start_dt.timestamp())
        a1 = int(end_dt.timestamp())
        if a1 < a0:
            a1 += 24 * 3600
        return a0, a1

    a0 = parse_timestamp(start)
    a1 = parse_timestamp(end)
    if a1 < a0:
        a1 += 24 * 3600
    return a0, a1


def merged_timeline_minutes(intervals: list[tuple[str, str]]) -> float:
    """Wall-clock minutes after merging overlapping segment intervals."""
    if not intervals:
        return 0.0

    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        try:
            a0, a1 = _segment_interval_seconds(start, end)
        except ValueError:
            continue
        if a1 <= a0:
            continue
        merged.append((a0, a1))

    if not merged:
        return 0.0

    merged.sort(key=lambda item: item[0])
    combined: list[tuple[int, int]] = [merged[0]]
    for a0, a1 in merged[1:]:
        last_start, last_end = combined[-1]
        if a0 <= last_end:
            combined[-1] = (last_start, max(last_end, a1))
        else:
            combined.append((a0, a1))

    total_seconds = sum(end - start for start, end in combined)
    return round(total_seconds / 60.0, 2)


def segments_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    a0_dt, a1_dt = _parse_instant(start_a), _parse_instant(end_a)
    b0_dt, b1_dt = _parse_instant(start_b), _parse_instant(end_b)
    if a0_dt and a1_dt and b0_dt and b1_dt:
        return max(a0_dt, b0_dt) < min(a1_dt, b1_dt)

    a0, a1 = parse_timestamp(start_a), parse_timestamp(end_a)
    b0, b1 = parse_timestamp(start_b), parse_timestamp(end_b)
    return max(a0, b0) < min(a1, b1)
