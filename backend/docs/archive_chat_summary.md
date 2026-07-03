# ProperData Billing Engine — Chat Summary

**Saved:** 2026-06-29  
**Project:** `c:\AllStar-CodeTest\ProperData`  
**Transcript ID:** `3f12d943-ec25-4614-8301-1cef14e5e131`

---

## Project Goal

Build a **Python FastAPI billing engine** that:

- Accepts session JSON (CPT codes, timestamps, diagnoses, transcript)
- Validates billing using **5 authoritative JSON files** + advisory **medexa_cpt_lookup.json**
- Prioritizes **ICD-10 medical necessity (diagnosis) validation**
- Auto-applies hard denials; flags bypassable NCCI conflicts for therapist modifier choice
- Applies **Medicare pooled 8-minute rule** for timed CPTs
- Returns structured JSON (optional follow-up: clearer human-readable explanations)

---

## Authoritative Data Files

| File | Role |
|------|------|
| `cpt_general_info.json` | Descriptions, `isEightMinuteRule` |
| `cpt_icd10_info.json` | CPT ↔ ICD-10 crosswalk (large, UTF-8 BOM) |
| `cpt_ptp_info.json` | NCCI bundling (`modifier_indicator` 0/1) |
| `cpt_mue_info.json` | Max units per CPT |
| `cpt_aoc_info.json` | Add-on parent rules |

**Advisory only:** `medexa_cpt_lookup.json` (transcript phrase matching — CPT only, no ICD)

**Spec:** `Billing_Engine_Architecture_Spec.md`

---

## Implementation (Completed)

```
ProperData/
  app/
    main.py              # GET /health, POST /billing/evaluate
    config.py
    models/input.py, output.py
    engine/
      loader.py          # utf-8-sig for JSON BOM
      duration.py        # HH:MM:SS + ISO8601 timestamps
      icd10.py           # exact ICD match; keys OR values
      aoc.py, ptp.py, mue.py, eight_minute.py
      transcript_medexa.py
      pipeline.py
  tests/                 # 15 pytest cases, all passing
  requirements.txt
  pytest.ini
  start-server.bat       # full-path Python launcher
```

**Tests:** `python -m pytest -q` → **15 passed**

---

## Key Product Decisions

- **Auto-apply** hard denials (invalid ICD, hard NCCI, missing add-on parent, MUE zero, unknown CPT)
- **Never auto-apply modifiers**; suggest 59/XE/XP/XS/XU when `modifier_indicator=1`
- **Transcript/medexa:** advisory only — never auto-remove codes for weak transcript
- **ICD extraction:** supports spec format (`icd_1: "M54.50"`) AND user format (`M75.00: "description"`) via ICD-10 regex on keys and values
- **Diagnosis-first** output ordering with `diagnosis_validation` section
- **Exact ICD match only** — no prefix/family inference (e.g. `M75.00` ≠ `M75.02`)

---

## Bugs Fixed During Testing

1. **500 error on ISO timestamps** — CPT segments used `2026-06-29T10:05:00Z` but `segments_overlap()` only handled `HH:MM:SS`. Fixed in `duration.py`.
2. **Diagnoses as ICD keys** — Engine was reading diagnosis *values* (descriptions) not *keys* (codes). Fixed in `icd10.py`.
3. **JSON BOM** — `cpt_icd10_info.json` has UTF-8 BOM; loader uses `encoding="utf-8-sig"`.
4. **Wrong uvicorn start** — Run from `ProperData` with `python -m uvicorn app.main:app`, not `uvicorn main:app` from `app/` subfolder.

---

## How to Run

```powershell
cd C:\AllStar-CodeTest\ProperData
& "$env:LocalAppData\Programs\Python\Python312\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Or use `start-server.bat`.

Swagger: http://127.0.0.1:8000/docs

**Note:** Python 3.12.10 may not be on PATH in Cursor terminals until restart; use full path or `start-server.bat`.

---

## Example Session Results

### John Doe (97140 + 97110 + 97116)

- Knee diagnoses: M25.661, M17.11, Z89.411
- Valid shoulder/knee session after ISO timestamp fix
- 40 timed minutes → 3 units under 8-minute rule
- Transcript weak for 97140/97116 (advisory only)

### Mary Smith OT (97140, 97530, 97129, 97130)

**Diagnoses submitted:** F06.8, M75.00, R41.841

| CPT | Result | Why |
|-----|--------|-----|
| 97140 | Removed | None of the three ICDs are in 97140's crosswalk |
| 97530 | Removed | Same — none of the three ICDs are in 97530's crosswalk |
| 97129 | Kept | R41.841 is valid for 97129 |
| 97130 | Kept | Add-on to 97129 (2 units, 30 timed min) |

### Robert Taylor (97016, 97140, 97530, 97550, 97551)

- All ICD valid via M51.26
- 6 total units; MUE caps on 97016 and 97550
- **Bypassable NCCI:** 97140 + 97530 need therapist modifier choice
- 97550 transcript supported; others weak

---

## ICD Crosswalk Clarification (Important)

**Question:** Do CPT codes 97140 and 97530 have no valid ICD-10 codes defined?

**Answer: No.** Both CPTs have large crosswalks in `cpt_icd10_info.json`:

| CPT | Valid ICD-10 codes in crosswalk |
|-----|--------------------------------|
| 97140 | **2,788** |
| 97530 | **2,864** |
| 97129 | **98** |

The Mary Smith removals were **not** because those CPTs lack ICD definitions. They were removed because **none of the three submitted diagnoses** appear in those CPT-specific lists:

| ICD submitted | In 97140? | In 97530? | In 97129? |
|---------------|-----------|-----------|-----------|
| F06.8 | No | No | No |
| M75.00 | No | No | No |
| R41.841 | No | No | **Yes** |

**Additional nuance:**

- **M75.00** does not appear anywhere in `cpt_icd10_info.json` (not for any CPT). Related codes like **M75.02** *are* present for 97140/97530.
- **F06.8** also does not appear anywhere in the crosswalk file.
- **R41.841** supports cognitive codes (97129) but not musculoskeletal 97140/97530.
- Engine uses **exact match only** — no prefix/family inference.

**Plain-language summary:**

- **Not:** "97140 and 97530 have no ICD-10 codes defined"
- **Yes:** "For 97140 and 97530, none of the three ICDs on this claim are in those CPTs' crosswalks"

If clinical intent is shoulder capsulitis, a code like **M75.02** (or another M75.xx actually in the file) would likely pass for 97140/97530.

---

## Medexa Analysis (Advisory Layer)

- 85 CPT entries in `medexa_cpt_lookup.json`
- Transcript support accuracy ~74/100 (with billing rules)
- Standalone CPT detection ~55/100
- Cannot validate ICD from medexa
- `cpt_conflict_analysis.md` documents co-firing/substring risks

**Accuracy scores (standalone transcript only):**

| Metric | Score |
|--------|-------|
| At least one correct CPT suggested | 68/100 |
| Exact match to final billable set | 48/100 |
| Precision | 62/100 |
| Recall | 58/100 |
| **Overall standalone** | **~55/100** |

---

## Not Yet Done / Optional Follow-ups

- **`human_summary` field** in API output (clearer text reports)
- **Transcript ICD validation** — deferred (no ICD keyword file)
- **`POST /transcript/suggest-cpts`** — phase 2
- **M75.00 added to crosswalk** or **ICD normalization** (prefix match) — not implemented
- Restart server after fixes using `start-server.bat` or full Python path

---

## Plan File

Updated plan: `c:\Users\DELL\.cursor\plans\fastapi_billing_engine_a23df930.plan.md`
