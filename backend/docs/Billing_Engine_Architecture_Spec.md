# Billing Engine System Specification

This document maps out the available resources, input data format, and exact expectations for the Billing Engine model to implement. 

---

## 1. Available System Resources

The system has access to five deterministic metadata files used for medical coding logic and validation. Each file contains a JSON array of objects keyed by `cpt_code`. 

Below is the strict definition of what each file contains and what its data actually means for the billing engine:

### 1.1 `cpt_icd10_info.json` (Medical Necessity Crosswalk)
*   **What it contains:** A mapping between a specific CPT code and an array of ICD-10 diagnosis codes.
    *   *Schema Example:* `{"cpt_code": "97168", "valid_icd10_codes": [{"code": "M50.01"}]}`
*   **What the data means:** This file dictates **Medical Necessity**. For a given CPT code to be approved for billing, the patient must be diagnosed with at least one ICD-10 code present in the `valid_icd10_codes` array. If an ICD-10 code submitted on a claim is not in this list for the CPT code, the service is generally considered not medically necessary and will be denied by insurance.

### 1.2 `cpt_ptp_info.json` (Procedure-to-Procedure / NCCI Edits)
*   **What it contains:** Rules defining which CPT codes cannot be billed together on the same date of service.
    *   *Schema Example:*
        ```json
        {
          "cpt_code": "97168",
          "ptp": {
            "bundled_into": [ {"modifier_indicator": "1", "primary_code": "0552T"} ],
            "bundles_others": [ {"modifier_indicator": "0", "bundled_code": "0359T"} ]
          }
        }
        ```
*   **What the data means:** This dictates **Bundling Conflicts**. 
    *   `bundled_into`: Indicates that the current CPT code is a smaller component of the `primary_code`. If both are billed, the component code is denied.
    *   `bundles_others`: Indicates the current CPT code is the comprehensive primary code, and the listed `bundled_code`s are smaller components that are absorbed into it.
    *   `modifier_indicator`: Crucial flag dictating if the bundle can be bypassed.
        *   `"0"`: **Hard Conflict**. No modifier is allowed. The codes cannot be billed together under any circumstance.
        *   `"1"`: **Bypassable Conflict**. The codes are bundled, but a modifier (e.g., 59, XE, XP, XS, XU) may be appended by the therapist to bypass the edit if the procedures were distinctly separate.

### 1.3 `cpt_mue_info.json` (Medically Unlikely Edits)
*   **What it contains:** Maximum unit limits per CPT code.
    *   *Schema Example:* `{"cpt_code": "99418", "mue": {"limit": 4, "adjudication": null, "adjudication_level": null, "description": "Clinical: Data"}}`
*   **What the data means:** `mue.limit` represents the absolute maximum number of units that a provider would report under most circumstances for a single patient on a single date of service. The engine must cap billed units at this limit to prevent automated denials for excessive billing.

### 1.4 `cpt_aoc_info.json` (Add-On Codes)
*   **What it contains:** Indicators for supplementary procedures.
    *   *Schema Example:* `{"cpt_code": "97546", "isAddonCode": true, "parentCode": "97545", "addonCodesAllowed": []}`
*   **What the data means:** Determines if a code is an Add-On Code (AOC). If `isAddonCode` is `true`, this CPT code represents a supplemental service that **cannot** be billed on its own. It is only valid if the base primary procedure, identified precisely by the `parentCode`, is also present on the same session claim. 

### 1.5 `cpt_general_info.json` (General Metadata & Time Flags)
*   **What it contains:** Base metadata and the crucial time-based flag.
    *   *Schema Example:* `{"cpt_code": "97750", "description": "Physical performance test...", "isEightMinuteRule": true}`
*   **What the data means:** `isEightMinuteRule` is a boolean flag that alters how units are calculated. 
    *   If `false`, the code is occurrence-based (usually billed as 1 unit per instance, capped by MUE). 
    *   If `true`, the code is time-based. Its units are not determined by occurrences, but rather by aggregating the total time of all time-based codes in the session and applying the CMS 8-Minute Rule algorithmic brackets (8-22 mins = 1 unit, 23-37 mins = 2 units, etc.).

---

## 2. Provided Input Format

The system will receive a JSON payload formatted as follows:

```json
{
  "client_info": {
    "client_name": "John Doe",
    "client_id": "PT-99482"
  },
  "session_metadata": {
    "session_start": "2026-06-29T10:00:00Z",
    "session_end": "2026-06-29T10:45:00Z"
  },
  "diagnoses": {
    "icd_1": "M54.50"
  },
  "billing_detection_summary": {
    "total_cpt_detected": 2
  },
  "detected_cpt_codes": [
    {
      "cpt_code": "97168",
      "sequence": 1,
      "timestamp_start": "00:02:15",
      "timestamp_end": "00:15:30"
    },
    {
      "cpt_code": "97110",
      "sequence": 2,
      "timestamp_start": "00:16:00",
      "timestamp_end": "00:42:15"
    }
  ],
  "whole_transcript": "Therapist: Good morning, John. Let's get started with your scheduled occupational therapy re-evaluation today... [Full conversation context continues here]"
}
```

---

## 3. Expectations & Rules

Using the five provided files and the input payload, the system is expected to perform the following evaluations:

1.  **ICD-10 Applicability:** Determine whether each specified CPT code is applicable and valid for the provided ICD-10 diagnosis code(s).
2.  **Conflict Detection:** Determine if there are any modifier or bundling conflicts among the billed CPT codes. 
3.  **8-Minute Rule Application:** Once the CPT codes are cleared, they must be billed using the 8-minute rule logic. This logic is applicable only to the subset of CPT codes (approximately 25-30) that fall under the category of the 8-minute rule.

---

## 4. Required Output Format

The engine must produce an output report containing:

1.  **Session & Unit Breakdown:** Each billed CPT code must be listed alongside its calculated session duration and its final assigned billed units.
2.  **Total Session Duration:** The total combined session duration based on the input timestamps.
3.  **User-Facing Conflict Resolution:** Any modifier conflicts that cannot be calculated automatically by the engine (and thus require proper input from the therapist) must be highlighted on the screen. The system must output clear recommendations to the therapist on what modifiers are applicable to bypass the edit and what modifiers are not applicable.
