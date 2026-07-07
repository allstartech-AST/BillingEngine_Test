import type { CptInputRow, LlmAuditResponse, TimingRuleset } from "../types/audit";

function billingRuleValue(ruleset: TimingRuleset): string {
  return ruleset === "AMA Rule of Eight" ? "ama_rule_of_8" : "cms_8_minute";
}

function parseAuditError(detail: unknown): string {
  const fallback = "OpenAI audit failed. Try again or check your API key and quota.";
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.message === "string") return record.message;
    if (typeof record.technical_detail === "string") return record.technical_detail;
  }
  return fallback;
}

export async function runComplianceAudit(
  rows: CptInputRow[],
  ruleset: TimingRuleset,
): Promise<LlmAuditResponse> {
  const payload = {
    billing_rule: billingRuleValue(ruleset),
    rows: rows
      .filter((row) => row.cptCode.trim())
      .map((row) => ({
        cpt: row.cptCode.trim(),
        duration_minutes: row.durationMinutes,
        body_region: row.bodyRegion.trim(),
      })),
  };

  const response = await fetch("/billing/compliance-audit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = (await response.json()) as LlmAuditResponse & { detail?: unknown };
  if (!response.ok) {
    throw new Error(parseAuditError(data.detail ?? data));
  }

  return data;
}
