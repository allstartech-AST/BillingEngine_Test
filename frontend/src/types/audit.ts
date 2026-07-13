export type TimingRuleset = "Medicare 8-Minute Rule" | "AMA Rule of Eight";

export interface CptInputRow {
  id: string;
  cptCode: string;
  durationMinutes: number;
  bodyRegion: string;
}

export interface LlmAuditResponse {
  rule_applied: "Medicare 8-Minute" | "AMA Rule of 8";
  total_billable_units: number;
  calculated_codes: Array<{
    cpt: string;
    units: number;
    explanation: string;
  }>;
  modifier_required: "59" | null;
  validation_status: "PASSED" | "FAILED";
  auditor_notes: string;
}

export interface EngineCodeResult {
  cpt: string;
  units: number;
  modifiers: string[];
  durationMinutes: number;
  description: string;
  bodyRegion: string;
}

export interface EngineBaselineResult {
  billingRule: string;
  totalUnits: number;
  codes: EngineCodeResult[];
  modifierSuggested: string | null;
  rawReport: BillingReport;
}

export interface BillingReport {
  billable_codes: Array<{
    cpt_code: string;
    description: string;
    duration_minutes: number;
    units: number;
    billing_rule: string | null;
  }>;
  billing_conflicts: Array<{
    conflict_id: string;
    codes: string[];
    modifier_indicator: string | null;
    recommendations: Array<{ action: string; modifiers: string[] }>;
  }>;
  ui_display: {
    summary_cards: {
      session_units_total: number;
      billing_rule: string;
      eight_minute_rule: boolean;
    };
    cpt_cards: Array<{
      cpt_code: string;
      units_display: number | string;
      applied_modifiers: string[];
      duration_display: string;
    }>;
  };
}

export interface ComparisonRow {
  cpt: string;
  engineUnits: number | null;
  llmUnits: number | null;
  engineModifiers: string[];
  llmModifierRequired: boolean;
  hasUnitMismatch: boolean;
  hasModifierMismatch: boolean;
  llmExplanation: string | null;
  bodyRegion: string;
}
