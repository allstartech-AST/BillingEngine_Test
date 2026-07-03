import { GoogleGenerativeAI, SchemaType, type ResponseSchema } from "@google/generative-ai";
import type { CptInputRow, LlmAuditResponse, TimingRuleset } from "../types/audit";

const GEMINI_AUDIT_MODEL =
  import.meta.env.VITE_GEMINI_AUDIT_MODEL || "gemini-2.5-flash";

const SYSTEM_PROMPT = `You are an expert US Healthcare Billing Compliance Auditor specializing in outpatient rehabilitation therapy (PT/OT/SLP) CPT coding.

Your role is to independently audit a proposed therapy session billing scenario using your regulatory knowledge — NOT any external lookup files or databases supplied by the user.

Evaluate using:
- CMS Medicare 8-Minute Rule (pooled timed minutes across timed CPT codes) OR AMA Rule of 8 (per-code timed thresholds), based on the selected ruleset
- Timed vs untimed CPT procedure definitions
- Cumulative unit thresholds for timed codes (8-22 min = 1 unit, 23-37 = 2 units, etc. under Medicare pooled rule; AMA applies per-code)
- Medically Unlikely Edit (MUE) unit limits where relevant
- NCCI Procedure-to-Procedure (PTP) bundling edits and when modifier 59 (or X-modifiers) may bypass a bundling conflict
- Anatomical / body region context when codes are region-specific or when distinct procedural regions may justify modifier 59

You MUST return ONLY valid JSON matching the required schema. Do not include markdown fences or commentary outside JSON.

If inputs are incomplete or ambiguous, set validation_status to FAILED and explain in auditor_notes.`;

const RESPONSE_SCHEMA: ResponseSchema = {
  type: SchemaType.OBJECT,
  properties: {
    rule_applied: {
      type: SchemaType.STRING,
      enum: ["Medicare 8-Minute", "AMA Rule of 8"],
      format: "enum",
    },
    total_billable_units: { type: SchemaType.NUMBER },
    calculated_codes: {
      type: SchemaType.ARRAY,
      items: {
        type: SchemaType.OBJECT,
        properties: {
          cpt: { type: SchemaType.STRING },
          units: { type: SchemaType.NUMBER },
          explanation: { type: SchemaType.STRING },
        },
        required: ["cpt", "units", "explanation"],
      },
    },
    modifier_required: {
      type: SchemaType.STRING,
      nullable: true,
    },
    validation_status: {
      type: SchemaType.STRING,
      enum: ["PASSED", "FAILED"],
      format: "enum",
    },
    auditor_notes: { type: SchemaType.STRING },
  },
  required: [
    "rule_applied",
    "total_billable_units",
    "calculated_codes",
    "modifier_required",
    "validation_status",
    "auditor_notes",
  ],
};

function getApiKey(): string | undefined {
  const key = import.meta.env.VITE_GEMINI_API_KEY as string | undefined;
  if (!key) {
    console.warn(
      "[LLM Validation Calculator] VITE_GEMINI_API_KEY is missing. Add it to .env.local in the project root and restart the Vite dev server.",
    );
  }
  return key;
}

function buildUserPrompt(rows: CptInputRow[], ruleset: TimingRuleset): string {
  const lines = rows.map(
    (row, index) =>
      `${index + 1}. CPT ${row.cptCode.trim()} | Duration: ${row.durationMinutes} minutes | Body Region: ${row.bodyRegion.trim() || "unspecified"}`,
  );

  return `Audit the following therapy session billing scenario.

Selected timing ruleset: ${ruleset === "AMA Rule of Eight" ? "AMA Rule of 8" : "Medicare 8-Minute Rule"}

CPT line items:
${lines.join("\n")}

Calculate billable units per code, total billable units, whether modifier 59 is required for NCCI bypass, validation status, and detailed auditor notes.`;
}

function normalizeAuditResponse(raw: LlmAuditResponse): LlmAuditResponse {
  const modifier =
    raw.modifier_required === "59" || raw.modifier_required === null
      ? raw.modifier_required
      : null;

  return {
    ...raw,
    modifier_required: modifier,
    calculated_codes: raw.calculated_codes.map((code) => ({
      ...code,
      cpt: code.cpt.trim(),
    })),
  };
}

function parseGeminiError(err: unknown): string {
  const fallback = "Gemini audit failed. Try again or check your API key and quota.";
  if (!(err instanceof Error)) return fallback;

  const message = err.message;
  const lower = message.toLowerCase();

  if (lower.includes("api key") && lower.includes("not configured")) {
    return "Gemini API key is not configured. Set VITE_GEMINI_API_KEY in .env.local.";
  }
  if (lower.includes("429") || lower.includes("resource_exhausted") || lower.includes("quota")) {
    if (lower.includes("limit: 0")) {
      return (
        "Gemini free-tier quota for this model is unavailable (limit: 0). " +
        "Use gemini-2.5-flash or enable billing in Google AI Studio."
      );
    }
    return "Gemini rate limit or quota exceeded. Wait and try again.";
  }
  if (lower.includes("401") || lower.includes("403") || lower.includes("invalid api key")) {
    return "Gemini rejected the API key. Verify VITE_GEMINI_API_KEY in .env.local.";
  }
  if (lower.includes("404") && lower.includes("model")) {
    return `Gemini model "${GEMINI_AUDIT_MODEL}" is not available for this API key.`;
  }
  return message || fallback;
}

export async function runGeminiAudit(
  rows: CptInputRow[],
  ruleset: TimingRuleset,
): Promise<LlmAuditResponse> {
  const apiKey = getApiKey();
  if (!apiKey) {
    throw new Error(
      "Gemini API key is not configured. Set VITE_GEMINI_API_KEY in .env.local.",
    );
  }

  const genAI = new GoogleGenerativeAI(apiKey);
  const model = genAI.getGenerativeModel({
    model: GEMINI_AUDIT_MODEL,
    systemInstruction: SYSTEM_PROMPT,
    generationConfig: {
      responseMimeType: "application/json",
      responseSchema: RESPONSE_SCHEMA,
      temperature: 0.1,
    },
  });

  let result;
  try {
    result = await model.generateContent(buildUserPrompt(rows, ruleset));
  } catch (err) {
    throw new Error(parseGeminiError(err));
  }

  const text = result.response.text();

  let parsed: LlmAuditResponse;
  try {
    parsed = JSON.parse(text) as LlmAuditResponse;
  } catch {
    throw new Error("Gemini returned malformed JSON. Try running verification again.");
  }

  return normalizeAuditResponse(parsed);
}

export function checkGeminiKeyOnLoad(): void {
  getApiKey();
}
