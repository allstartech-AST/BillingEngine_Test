# Billing Engine — Phase 2 Plan

**Location:** [`docs/BILLING_ENGINE_PHASE2_PLAN.md`](BILLING_ENGINE_PHASE2_PLAN.md)

**Data files:** `data/billing/` (CMS JSON) and `data/medexa/` (lookup JSON).

Cursor also stores plans under:
- `C:\Users\DELL\.cursor\plans\billing_engine_phase2.plan.md` (current phase 2)
- `C:\Users\DELL\.cursor\plans\icd_transcript_validation_5065724e.plan.md` (phase 1 + human summary)
- `C:\Users\DELL\.cursor\plans\fastapi_billing_engine_a23df930.plan.md` (original build)

---

## Phase 2 todos

| ID | Task | Status |
|----|------|--------|
| billing-detection-summary | Reconcile `billing_detection_summary` vs `detected_cpt_codes` | done |
| cpt-matcher-replace | **Replace** `transcript_medexa.py` matching with [`cpt_code_finder.py`](cpt_code_finder.py) `CPTMatcher` | done |
| transcript-aggregate-scoring | Aggregate all sentence hits; +5 per extra sentence, cap 100 | done |
| icd-semantic-necessity | Semantic CPT↔ICD confidence; pending if <100 | done |
| ptp-column-guidance | Column 1 + Column 2 + modifier on column two | done |
| eight-minute-rounding | Seconds precision; 30s rounding before 8-min pool | done |
| tests-phase2 | Golden tests for all above | done |

---

## 1. `billing_detection_summary`

**Shape A (spec):** `{ "total_cpt_detected": 2 }` — detector count.

**Shape B (your sessions):** `{ "97140": {}, "97110": {} }` — **keys = CPT codes detector flagged**; values = future per-code metadata.

**`detected_cpt_codes`** = same CPTs with sequences + timestamps (**authoritative for billing**).

Engine reconciles both shapes against segments; warns on mismatch; never adds/removes CPTs from summary alone.

---

## 2. Replace keyword matching with `cpt_code_finder.py`

### Why replace current [`app/engine/transcript_medexa.py`](app/engine/transcript_medexa.py)

Current engine uses **literal substring** matching (`phrase in sentence`) with a small word-boundary list. That fails on natural speech:

- "therapeutic **exercises**" vs trigger "therapeutic exercise"
- Words inserted between phrase tokens
- Trailing modifiers ("electrical stimulation **unattended**")

### Source of truth: [`cpt_code_finder.py`](cpt_code_finder.py)

Standalone matcher already implements the intended design:

| Feature | Implementation |
|---------|----------------|
| Data file | **`medexa_cpt_lookup.json`** (NOT `medexa_cpt_lookup_efficient.json`) |
| Phrase match | Subsequence + gap tolerance (`max_gap=2`) |
| Order fallback | Unordered window match for reordered clinical terms |
| Stemming | Lightweight stemmer + irregular verbs (`exercise`/`exercises`, `did`→`do`) |
| Context | `required_context` within 10 tokens of trigger span |
| Action fallback | `_GENERIC_ACTION_VERBS` when JSON context list misses natural phrasing |
| Exclusions | `exclude_if_present` in **same sentence** |
| Segmentation | Sentence split + speaker-label strip + bracket annotation strip |

### Integration plan

1. **Move** matcher into app package:
   - `app/engine/cpt_matcher.py` — refactor from [`cpt_code_finder.py`](cpt_code_finder.py) (remove CLI/`analyze_transcript` bottom section)
   - Keep `CPTMatcher`, `CodeMatch`, stem/phrase helpers

2. **Wire loader** — `CPTMatcher` loads from `MEDEXA_FILE` path in [`app/config.py`](app/config.py) (`medexa_cpt_lookup.json`)

3. **Replace** `_evaluate_medexa_entry()` in `transcript_medexa.py`:
   - For CPT: `CPTMatcher.match(transcript)` filtered to requested `cpt_code`, OR new method `CPTMatcher.match_code(transcript, cpt_code)`
   - Map `CodeMatch` hits → `TranscriptCptSupport` (supported + evidence)

4. **ICD transcript validation** — reuse same matching **core** (`find_phrase_span`, `context_within_distance`, stemmer) against `medexa_icd10_lookup.json` entries (same schema: `trigger_phrases`, `required_context`, `exclude_if_present`)
   - New `ICDMatcher` class or generic `MedexaLookupMatcher(lookup_dict)`

5. **Do NOT use** `medexa_cpt_lookup_efficient.json` — [`cpt_code_finder.py`](cpt_code_finder.py) documents why (rigid pre-multiplied phrases, 16k+ lines, poor natural speech match)

6. **Aggregate scoring** (phase 2) on top of matcher results:
   - Collect all non-excluded `CodeMatch` hits across sentences for a code
   - Base score from best hit; +5 per additional supporting sentence; cap 100
   - Multiple hits per code allowed (matcher already tracks per sentence)

7. **Optional:** populate `billing_detection_summary` reconciliation by comparing summary CPT keys to `CPTMatcher.summarize(transcript)` keys (detector manifest vs transcript re-match)

### Files to change

| File | Action |
|------|--------|
| [`cpt_code_finder.py`](cpt_code_finder.py) | Keep as reference; logic moves into `app/engine/` |
| `app/engine/cpt_matcher.py` | **New** — production matcher module |
| [`app/engine/transcript_medexa.py`](app/engine/transcript_medexa.py) | Delegate CPT/ICD validation to matcher; keep output models + confidence |
| [`tests/test_transcript_medexa.py`](tests/test_transcript_medexa.py) | Update for stemmed/gap-tolerant matches |
| `tests/test_cpt_matcher.py` | **New** — port cases from cpt_code_finder behavior |

---

## 3. Medical necessity — semantic CPT↔ICD

| Case | Result |
|------|--------|
| CPT not in `cpt_icd10_info.json` | Pass — `valid_no_crosswalk` |
| Empty `valid_icd10_codes[]` | Semantic confidence only |
| Exact ICD in crosswalk | Pass — `valid` |
| ICD not in list | Semantic CPT description ↔ ICD label/lookup |
| Confidence 100 | Confirmed |
| Confidence < 100 | `pending_icd_review` — do not auto-remove |

New: `app/engine/icd_semantic.py`

---

## 4. PTP — Column 1 + Column 2

`column_one` = primary (`primary_code`), `column_two` = component (bundled CPT).

Both codes + descriptions in conflict block; modifier on column two for bypassable bundles.

---

## 5. Eight-minute rule

Duration in seconds → round to whole minutes (≥30s up, ≤29s down) → pooled 8-min rule.

Output: `duration_minutes_exact` + `duration_minutes_billed`.

---

## Locked decisions

- Plans copied to project root for visibility
- **Matcher:** `cpt_code_finder.py` / `CPTMatcher` replaces current substring medexa matching
- **Lookup file:** `medexa_cpt_lookup.json` only (not `_efficient`)
- Detection summary: both formats, reconcile only
- Pending units: bypassable NCCI + `pending_icd_review`
