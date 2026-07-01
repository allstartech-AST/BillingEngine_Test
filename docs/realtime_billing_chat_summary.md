# Realtime 8-Minute Billing Engine — Chat Summary

**Saved:** 2026-06-29  
**Project:** `c:\AllStar-CodeTest\ProperData`  
**Transcript ID:** `3f12d943-ec25-4614-8301-1cef14e5e131`  
**Plan reference:** `realtime_billing_engine_81ba49fc.plan.md` (do not edit plan file)

---

## Product Scope (Locked in Conversation)

This engine is **solely for catching and billing CPTs under the 8-minute rule**:

- Detect timed CPTs incrementally
- Collect duration per CPT, pool minutes, calculate units
- Flag NCCI/MUE/ICD issues that block or hold timed units
- **Not** a full claim scrubber, occurrence/modality billing engine, or STT detection path

Batch `POST /billing/evaluate` + transcript pipeline remain for regression/fixtures only.

---

## What Was Implemented

### Live session API (`app/main.py`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/live/session` | Create session |
| POST | `/live/session/{id}/icd` | Add ICD(s), comma-separated OK |
| POST | `/live/session/{id}/cpt/detect` | Detect CPT (no duration yet) |
| POST | `/live/session/{id}/cpt/end` | End CPT with duration → pooled units |
| POST | `/live/session/{id}/modifier` | Approve/reject conflict |
| POST | `/live/session/{id}/end` | Finalize session |
| GET | `/live/session/{id}` | Current state |

### Core modules

- `app/models/live.py` — session state, CPT rows, payloads
- `app/engine/realtime/store.py` — in-memory session registry
- `app/engine/realtime/orchestrator.py` — event handlers
- `app/engine/realtime/rules.py` — incremental PTP/AOC/MUE/ICD checks
- `app/engine/realtime/ui_display.py` — live UI cards (no transcript fields)

### Prototype UI (`app/static/prototype.html`)

- **Live Session** tab: ICD input, CPT detect/end, demo script
- Auto-starts session on first action
- `/health` checks `live_api: true`
- CPT input **locked** until current CPT is ended with duration
- Cannot detect next CPT until open CPT is ended (backend + UI)

### Tests

- `tests/test_realtime_session.py` — 16+ scenarios
- Full suite: **64–65 tests passing**

---

## Live Session Flow

1. Add ICD(s) — all shown on **one ICD card**
2. **Detect CPT** — shows 8-minute vs manual badge, ICD validity; no units yet
3. **End CPT** with duration — pooled units calculated; duration + units on card
4. Detect next CPT — incremental PTP/AOC/MUE/ICD vs prior timed CPTs
5. NCCI bypassable conflict → units zeroed, modifier pills, approve/reject
6. **End session** — blocked if open CPT or unresolved conflicts

---

## Key Fixes During Session

| Issue | Fix |
|-------|-----|
| Buttons return **404 Not Found** | Stale uvicorn on port 8000 without `/live/*` routes; restart server |
| Only 1 unit shown | 8–22 pooled min = 1 unit; need 23+ min (or multiple timed CPTs) for 2+ |
| Unknown CPT shows error card | Rejected with status message only, no card |
| Manual CPTs | Duration shown; units display **Manual**; not auto-calculated |
| Stale "provide duration when CPT ends" after end | UI derives message from lifecycle; filters detect-phase suggestions |
| 97010 "removed" with confusing ICD text | **MUE limit 0** (not NCCI mod 0); clear removal reason label |
| Multiple ICDs / ICD after CPT | Re-validates all CPTs; single combined ICD card |
| Detect next CPT before ending current | Blocked; CPT code stays in locked input until end |

---

## Authoritative Data (What Engine Loads)

From `data/billing/` via `app/engine/loader.py`:

| File | Role for 8-min engine |
|------|------------------------|
| `cpt_general_info.json` | **Critical** — `isEightMinuteRule` gate |
| `cpt_ptp_info.json` | **Critical** — NCCI among active CPTs |
| `cpt_mue_info.json` | Caps / MUE zero hard blocks |
| `cpt_icd10_info.json` | Medical necessity crosswalk |
| `cpt_aoc_info.json` | Add-on parent rules (secondary) |

**Not loaded by engine:**

- `ncci_rules.json` (repo root) — spec/future; body region, unit thresholds, curated pairs
- `cpt_lookup.json` — STT phrase lookup; cut from live path

**Coverage:** 104 CPTs in all billing JSON files.

---

## Brutal Review: Are 5 JSONs Enough for Modifier Conflicts?

**Detection (timed CPT pairs):** Mostly yes, via `cpt_ptp_info.json` when both codes are on session.

**Resolution:** No. Approve = boolean bypass + unit recalc, not stored modifier on claim line.

**Gaps even for 8-min scope:**

- No body region on CPT rows → bypassable conflicts always fire
- `ncci_rules.json` diverges from PTP (e.g. 97110↔97530 in rules, not in PTP)
- No temporal overlap in live path
- No structured `{modifier, applies_to, approver, timestamp}` audit record
- No claim-line output for downstream billing

---

## Production-Grade Gaps (8-Minute Scope)

### Must-have before production

1. **Scope lock** — reject non–8-minute-rule CPTs in live detect
2. **Durable sessions** — not in-memory dict; survive restart, multi-instance
3. **Visit/patient/therapist IDs** + append-only event log
4. **Per-CPT timestamps** (or explicit duration attestation with audit)
5. **Billable output model** — lines with CPT, units, modifiers, DX pointers
6. **Structured conflict resolution** — not just UI approve flag
7. **Metadata versioning** — quarterly CMS PTP refresh, rules-as-of date on session
8. **Auth + audit** on mutating endpoints
9. **Finalize/sign gate** — block if open CPT or unresolved timed-CPT conflicts
10. **E2E integration tests** for full live timeline

### Current prototype limitations

- Duration typed manually at end (no per-code clock)
- Same CPT twice in one visit not modeled (one row per code)
- ~104 CPT subset; codes outside set = no rule evaluation
- Batch/transcript/manual-billing paths still in codebase (scope bleed)

---

## Run Commands

```powershell
cd C:\AllStar-CodeTest\ProperData
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
python -m pytest -q
```

- Prototype: http://127.0.0.1:8000/prototype  
- Hard refresh (Ctrl+F5) after code changes  
- If 404 on live routes: kill stale process on port 8000 and restart

---

## 8-Minute Rule Reference

Pooled across **completed timed CPTs**:

| Pooled minutes | Total units |
|----------------|-------------|
| 8–22 | 1 |
| 23–37 | 2 |
| 38–52 | 3 |

Units split across timed CPTs by remainder allocation (`app/engine/eight_minute.py`).

---

## Files Touched (Implementation)

```
app/models/live.py
app/models/output.py          # UiIcdCard.detected_icd10_codes
app/main.py                   # /live/* routes, /health live_api
app/engine/realtime/
  store.py
  orchestrator.py
  rules.py
  ui_display.py
app/static/prototype.html
app/static/prototype.css
tests/test_realtime_session.py
```

---

## Recommended Next Steps

1. Reject non-timed CPTs in `on_cpt_detected` (align code with scope)
2. Add `BillableLine` output on session end
3. Persist sessions (Postgres/Redis) + event log
4. Wire PTP only (drop or ignore `ncci_rules.json` until unified)
5. Store modifier approval as structured resolution record
