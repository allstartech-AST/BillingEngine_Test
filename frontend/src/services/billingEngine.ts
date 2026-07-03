import type {
  BillingReport,
  CptInputRow,
  EngineBaselineResult,
  TimingRuleset,
} from "../types/audit";

function formatTimestamp(totalMinutes: number): string {
  const wholeMinutes = Math.floor(totalMinutes);
  const seconds = Math.round((totalMinutes - wholeMinutes) * 60);
  const hours = Math.floor(wholeMinutes / 60);
  const minutes = wholeMinutes % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function billingRuleValue(ruleset: TimingRuleset): string {
  return ruleset === "AMA Rule of Eight" ? "ama_rule_of_8" : "cms_8_minute";
}

export function buildEvaluationPayload(
  rows: CptInputRow[],
  ruleset: TimingRuleset,
) {
  let cumulativeMinutes = 0;
  const detectedCptCodes = rows.map((row, index) => {
    const startMinutes = cumulativeMinutes;
    cumulativeMinutes += row.durationMinutes;
    return {
      cpt_code: row.cptCode.trim(),
      sequence: index + 1,
      timestamp_start: formatTimestamp(startMinutes),
      timestamp_end: formatTimestamp(cumulativeMinutes),
    };
  });

  const sessionStart = "2026-07-01T10:00:00Z";
  const sessionEnd = new Date(
    Date.parse(sessionStart) + cumulativeMinutes * 60_000,
  ).toISOString();

  return {
    client_info: {
      client_name: "LLM Validation Test",
      client_id: "VAL-001",
    },
    session_metadata: {
      session_start: sessionStart,
      session_end: sessionEnd,
    },
    diagnoses: {
      icd_1: "M54.50",
    },
    detected_cpt_codes: detectedCptCodes,
    billing_rule: billingRuleValue(ruleset),
    whole_transcript: rows
      .map(
        (row) =>
          `${row.cptCode} for ${row.bodyRegion || "unspecified region"} lasting ${row.durationMinutes} minutes`,
      )
      .join(". "),
  };
}

function extractSuggestedModifier(report: BillingReport): string | null {
  for (const conflict of report.billing_conflicts) {
    if (conflict.modifier_indicator === "1") {
      for (const rec of conflict.recommendations) {
        if (rec.modifiers.length > 0) {
          return rec.modifiers[0];
        }
      }
    }
  }
  return null;
}

export async function runLocalEngineEvaluation(
  rows: CptInputRow[],
  ruleset: TimingRuleset,
): Promise<EngineBaselineResult> {
  const payload = buildEvaluationPayload(rows, ruleset);
  const response = await fetch("/billing/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = (await response.json()) as BillingReport & { detail?: unknown };
  if (!response.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail ?? response.statusText);
    throw new Error(detail);
  }

  const modifierMap = new Map<string, string[]>();
  for (const card of data.ui_display.cpt_cards) {
    modifierMap.set(card.cpt_code, card.applied_modifiers ?? []);
  }

  const regionMap = new Map(rows.map((row) => [row.cptCode.trim(), row.bodyRegion]));

  const codes = data.billable_codes.map((code) => ({
    cpt: code.cpt_code,
    units: code.units,
    modifiers: modifierMap.get(code.cpt_code) ?? [],
    durationMinutes: code.duration_minutes,
    description: code.description,
    bodyRegion: regionMap.get(code.cpt_code) ?? "",
  }));

  return {
    billingRule: data.ui_display.summary_cards.billing_rule,
    totalUnits: data.ui_display.summary_cards.session_units_total,
    codes,
    modifierSuggested: extractSuggestedModifier(data),
    rawReport: data,
  };
}
