# CPT Conflict Analysis — `medexa_cpt_lookup.json`

Analysis of [medexa_cpt_lookup.json](file:///c:/Billing-Engine-Test/medexa_cpt_lookup.json) for keyword-search conflicts when matching against clinical transcripts.

**File Stats:** 67 CPT codes, ~400 trigger phrases, 22 NCCI conflict pairs declared.

---

## 1. Trigger Phrase Overlap — Codes That Will Co-Fire

These are the most dangerous conflicts: a single transcript sentence can match **multiple CPT codes simultaneously** because the trigger phrases are substrings of each other or share identical root phrases.

### 🔴 Critical Overlaps

| Phrase in Transcript | Codes That Fire | Why It's a Problem |
|---|---|---|
| `"therapeutic exercise"` | **97110** | Clean — but see below |
| `"therapeutic activities"` | **97530** | Clean — but see below |
| `"therapeutic"` (alone, near "exercise" AND "activity") | **97110 + 97530** | A transcript like *"continued therapeutic exercises and therapeutic activities"* fires both. These are NCCI conflicts requiring Mod 59, but **your engine has no body-region disambiguation**, so it can't determine if Mod 59 applies. |
| `"balance training"` | **97112** (Neuromuscular Reeducation) | But a therapist saying *"balance training on the stairs"* could also match **97116** (`"stair training"`) → dual fire |
| `"transfer training"` | **97530** (Therapeutic Activities) | But transfer training is often documented alongside **97535** (`"adl training"`, `"self care training"`) — dual fire likely |
| `"soft tissue mobilization"` | **97140** (Manual Therapy) | And `"soft tissue massage"` → **97124** (Massage). A transcript saying *"soft tissue mobilization and massage"* fires both — these are NCCI conflicts |
| `"manual traction"` | **97140** (Manual Therapy) | But 97012 has `"manual traction"` in its `exclude_if_present` — good. However, the phrase `"traction"` alone could still ambiguously match if transcript normalization strips qualifiers |
| `"gait training"` | **97116** | But `"gait reeducation"` also fires **97116**, while `"neuromuscular reeducation"` fires **97112**. The word `"reeducation"` is shared between contexts |
| `"feeding therapy"` | **92526** (SLP Swallowing) | And `"oral motor treatment"` fires **92526** — but an OT doing `"oral motor"` work within `"sensory integration"` could also fire **97533** |
| `"caregiver training"` | **97550** (Caregiver Training) | And `"aba caregiver training"` → **97156** (Family ABA Guidance). Transcript with *"caregiver training"* in an ABA context fires both |

### 🟡 Moderate Overlaps

| Phrase in Transcript | Codes That Fire | Risk |
|---|---|---|
| `"home program training"` | **97535** | Could co-fire with **97550** if `"caregiver"` is nearby (caregiver home program instruction) |
| `"functional mobility training"` | **97530** | Overlaps semantically with **97116** (`"ambulation training"`, `"walking training"`) |
| `"proprioception training"` / `"proprioceptive training"` | **97112** | Could co-fire with **97530** if transcript also mentions `"functional movement training"` |
| `"motor relearning"` | **97112** | Semantically close to `"motor control retraining"` (also 97112, fine) but could appear alongside `"task specific training"` → **97530** |

---

## 2. NCCI Conflict Pairs — Declared but Not Enforced at Match Time

The file declares `ncci_conflicts` arrays, but these only flag post-match. The keyword search itself will **happily return both sides of a conflict**. Here are the declared pairs:

```
97110 ↔ 97530    (Ther Ex vs Ther Act)
97112 ↔ 97530    (NMR vs Ther Act)
97116 ↔ 97530    (Gait vs Ther Act)
97140 ↔ 97530    (Manual Therapy vs Ther Act)
97140 ↔ 97110    (Manual Therapy vs Ther Ex)
97140 ↔ 97124    (Manual Therapy vs Massage)
97124 ↔ 97140    (Massage vs Manual Therapy)
97014 ↔ 97032    (Unattended vs Attended E-Stim)
97129 ↔ 97130    (Cognitive Initial vs Add-on)
97760 ↔ 97761    (Orthotic vs Prosthetic)
97161 ↔ 97162 ↔ 97163  (PT Eval complexity tiers)
97165 ↔ 97166 ↔ 97167  (OT Eval complexity tiers)
97169 ↔ 97170 ↔ 97171  (AT Eval complexity tiers)
92522 ↔ 92523    (Speech Sound vs Comprehensive)
97597 ↔ 97602    (Selective vs Non-Selective Debridement)
97810 ↔ 97813    (Acupuncture vs Electroacupuncture)
97605 ↔ 97606 ↔ 97607 ↔ 97608  (NPWT variants)
```

> [!WARNING]
> **97530 is the "magnet" code** — it has NCCI conflicts with **4 other codes** (97110, 97112, 97116, 97140), all of which are extremely common in PT/OT transcripts. A typical PT treatment session transcript will almost certainly co-fire 97530 with at least one of these.

---

## 3. Short / Ambiguous Trigger Phrases — High False-Positive Risk

These trigger phrases are dangerously short or common and will match unintended transcript content:

| Phrase | Code | Problem |
|---|---|---|
| `"tens"` | **97014** | Matches the word "tens" in casual speech (e.g., *"tens of repetitions"*, *"patient did tens of squats"*). Needs case-sensitive or bounded match. |
| `"ther ex"` | **97110** | Abbreviation — fine if transcript uses clinical shorthand, but fragile |
| `"ther act"` | **97530** | Same as above |
| `"mfr"` | **97140** | 3-letter abbreviation. Could appear as part of other acronyms |
| `"fce"` | **97750** | 3-letter abbreviation |
| `"nmes"` | **97032** | 4-letter — reasonably safe |
| `"lllt"` | **97037** | 4-letter — reasonably safe |
| `"iastm"` | **97140** | 5-letter — safe but also appears in 97124's `exclude_if_present` (good) |
| `"massage"` | **97124** | Very generic. *"Patient reported getting a massage over the weekend"* would fire this code |
| `"lsvt"` | **92507** | 4-letter — reasonably safe in SLP context |
| `"w/c training"` | **97542** | Special character `/` — ensure your normalizer preserves it or has an alternate |
| `"at evaluation"` / `"at eval"` | **97169** | The word `"at"` is a common preposition. If matching is loose, *"looked at evaluation results"* fires this |
| `"group session"` | **97150** | Very generic. *"Discussed in group session"* (staff meeting context) would fire |
| `"sensory diet"` | **97533** | Could appear in parent education context without actual treatment |

> [!CAUTION]
> `"tens"`, `"massage"`, `"at evaluation"`, and `"group session"` are the highest false-positive risks. They will fire on conversational language that isn't describing a billable service.

---

## 4. `required_context` Gaps

Several codes have **very weak or empty** `required_context`, meaning ANY trigger phrase match fires the code with no secondary validation:

| Code | Label | `required_context` | Risk |
|---|---|---|---|
| **97542** | Wheelchair Management | `[]` (empty) | Any mention of "wheelchair training" fires with zero confirmation |
| **97034** | Contrast Baths | `[]` (empty) | Same |
| **97036** | Hubbard Tank | `[]` (empty) | Same |
| **97039** | Unlisted Modality | `[]` (empty) | Same |
| **97139** | Unlisted Procedure | `[]` (empty) | Same |
| **97799** | Unlisted PM&R | `[]` (empty) | Same |
| **92526** | Swallowing Treatment | `[]` (empty) | `"feeding therapy"` fires with no context check |
| **97130** | Cognitive Add-on | `[]` (empty) | Engine-generated — OK |
| **97546** | Work Hardening Add-on | `[]` (empty) | Engine-generated — OK |
| **97551** | Caregiver Add-on | `[]` (empty) | Engine-generated — OK |
| **90913** | Biofeedback | `[]` (empty) | Any mention fires |
| **97116** | Gait Training | `["worked on"]` | Only 1 context word — weak |
| **97545** | Work Hardening | `["program"]` | Only 1 context word — weak |

---

## 5. `exclude_if_present` Inconsistencies

| Issue | Affected Codes | Detail |
|---|---|---|
| `"plan to"` is excluded in most codes but NOT all | **97533**, **97542** (partially), **90913**, **97150**, **97153** | A therapist saying *"plan to do sensory integration next session"* would fire 97533 |
| Evaluation exclusions are inconsistent | **97110** excludes `"evaluated"` but **97116** excludes `"evaluated gait"` (more specific) | If transcript says *"evaluated patient and did gait training"*, 97110 is correctly suppressed but 97116 fires — which is correct behavior, but the inconsistency pattern is risky |
| `"assessment"` exclusion gaps | **97530** excludes `"assessed"` but not `"assessment"` | Inconsistent with 97110 which excludes `"assessment"` |
| Missing `"recommended"` / `"referral"` | Nearly all codes | A transcript saying *"recommended massage therapy"* would fire 97124 even though no treatment was performed |

---

## 6. Cross-Discipline Collision Risk

| Scenario | Codes That Fire | Problem |
|---|---|---|
| OT + SLP session mentioning "cognitive" work | **97129** (Cognitive Intervention) + **92507** (Speech Treatment) | Both could fire if transcript mentions `"cognitive linguistic therapy"` (trigger for 97129) alongside `"speech therapy"` (trigger for 92507) |
| PT session with both exercises and manual work | **97110** + **97140** + **97530** | Classic triple-fire scenario. All three are NCCI conflicts with each other |
| Caregiver present during ABA session | **97550** + **97156** | `"caregiver training"` fires 97550; `"aba caregiver training"` fires 97156. Substring issue — 97156's phrase contains 97550's phrase |

---

## 7. Summary of Recommendations

> [!IMPORTANT]
> ### Must-Fix Before Production
> 1. **Add word-boundary matching** — `"tens"`, `"at eval"`, `"massage"`, and `"group session"` will generate excessive false positives without it
> 2. **Enforce NCCI conflicts at match time**, not just post-hoc — especially the 97530 "magnet" problem
> 3. **Add `"recommended"`, `"referral"`, `"discussed"`, `"considering"` to a global exclusion list** — these indicate non-performed services
> 4. **Add `"plan to"` exclusion to ALL treatment codes** — currently missing from ~8 codes
> 5. **Strengthen `required_context` for codes with empty arrays** — especially 92526, 97542, 90913

> [!TIP]
> ### Nice-to-Have Improvements
> 6. **Substring containment guard** — `"aba caregiver training"` should suppress `"caregiver training"` match (longest-match-wins)
> 7. **Case-sensitive matching for abbreviations** — `TENS`, `FCE`, `MFR`, `IASTM` should be uppercase-only
> 8. **Proximity window for `required_context`** — currently specified as "within 10 tokens" in `_meta` but there's no enforcement mechanism in the data structure itself
> 9. **Add a `"confidence"` tier** to trigger phrases — exact clinical terms (e.g., `"neuromuscular reeducation"`) should rank higher than casual language (e.g., `"balance training"`)
> 10. **Body-region tagging** — without it, the engine cannot determine if two NCCI-conflicting codes are targeting different body regions (which would legitimize Mod 59 billing)
