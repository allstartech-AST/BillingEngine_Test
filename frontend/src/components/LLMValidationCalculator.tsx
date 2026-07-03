import { useEffect, useMemo, useState } from "react";
import { runLocalEngineEvaluation } from "../services/billingEngine";
import { checkGeminiKeyOnLoad, runGeminiAudit } from "../services/geminiAudit";
import type {
  CptInputRow,
  EngineBaselineResult,
  LlmAuditResponse,
  TimingRuleset,
} from "../types/audit";
import DiscrepancyComparison, {
  buildComparisonRows,
} from "./DiscrepancyComparison";
import EngineBaselinePanel from "./EngineBaselinePanel";

const COMMON_CPT_CODES = [
  "97110",
  "97112",
  "97116",
  "97140",
  "97530",
  "97535",
  "97150",
  "97161",
  "97162",
  "97163",
  "97164",
  "97165",
  "97166",
  "97167",
  "97168",
  "97750",
  "97755",
  "97760",
  "97761",
  "97763",
];

const BODY_REGIONS = [
  "Cervical spine",
  "Thoracic spine",
  "Lumbar spine",
  "Shoulder",
  "Elbow",
  "Wrist / hand",
  "Hip",
  "Knee",
  "Ankle / foot",
  "Pelvic floor",
  "Whole body / general",
];

function createRow(partial?: Partial<CptInputRow>): CptInputRow {
  return {
    id: crypto.randomUUID(),
    cptCode: partial?.cptCode ?? "97110",
    durationMinutes: partial?.durationMinutes ?? 15,
    bodyRegion: partial?.bodyRegion ?? "Shoulder",
  };
}

export default function LLMValidationCalculator() {
  const [rows, setRows] = useState<CptInputRow[]>([
    createRow({ cptCode: "97110", durationMinutes: 16, bodyRegion: "Shoulder" }),
    createRow({ cptCode: "97140", durationMinutes: 15, bodyRegion: "Shoulder" }),
  ]);
  const [ruleset, setRuleset] = useState<TimingRuleset>("Medicare 8-Minute Rule");
  const [loading, setLoading] = useState(false);
  const [engineResult, setEngineResult] = useState<EngineBaselineResult | null>(null);
  const [llmResult, setLlmResult] = useState<LlmAuditResponse | null>(null);
  const [engineError, setEngineError] = useState<string | null>(null);
  const [llmError, setLlmError] = useState<string | null>(null);

  useEffect(() => {
    checkGeminiKeyOnLoad();
  }, []);

  const regionMap = useMemo(
    () => new Map(rows.map((row) => [row.cptCode.trim(), row.bodyRegion])),
    [rows],
  );

  const comparisonRows = useMemo(() => {
    if (!engineResult || !llmResult) return [];
    return buildComparisonRows(
      engineResult.codes,
      llmResult.calculated_codes,
      llmResult.modifier_required,
      engineResult.modifierSuggested,
      regionMap,
    );
  }, [engineResult, llmResult, regionMap]);

  const totalMismatch =
    engineResult != null &&
    llmResult != null &&
    engineResult.totalUnits !== llmResult.total_billable_units;

  function updateRow(id: string, patch: Partial<CptInputRow>) {
    setRows((current) =>
      current.map((row) => (row.id === id ? { ...row, ...patch } : row)),
    );
  }

  function addRow() {
    setRows((current) => [...current, createRow()]);
  }

  function removeRow(id: string) {
    setRows((current) =>
      current.length === 1 ? current : current.filter((row) => row.id !== id),
    );
  }

  async function handleRunVerification() {
    const validRows = rows.filter((row) => row.cptCode.trim());
    if (validRows.length === 0) {
      setEngineError("Add at least one CPT code before running verification.");
      return;
    }

    setLoading(true);
    setEngineError(null);
    setLlmError(null);
    setEngineResult(null);
    setLlmResult(null);

    const [engineOutcome, llmOutcome] = await Promise.allSettled([
      runLocalEngineEvaluation(validRows, ruleset),
      runGeminiAudit(validRows, ruleset),
    ]);

    if (engineOutcome.status === "fulfilled") {
      setEngineResult(engineOutcome.value);
    } else {
      setEngineError(
        engineOutcome.reason instanceof Error
          ? engineOutcome.reason.message
          : String(engineOutcome.reason),
      );
    }

    if (llmOutcome.status === "fulfilled") {
      setLlmResult(llmOutcome.value);
    } else {
      setLlmError(
        llmOutcome.reason instanceof Error
          ? llmOutcome.reason.message
          : String(llmOutcome.reason),
      );
    }

    setLoading(false);
  }

  return (
    <section className="space-y-6">
      <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
        <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
              Independent Auditor
            </p>
            <h2 className="text-xl font-extrabold text-ast-navy">
              LLM Validation Calculator
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Manually enter CPT scenarios and compare local engine math against Gemini compliance auditing.
            </p>
          </div>
          <div className="inline-flex items-center gap-1.5 rounded-full border border-ast-blue/10 bg-ast-tint px-3 py-1 text-[10px] font-bold uppercase tracking-wide text-ast-blue">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z" />
            </svg>
            Gemini 2.5 Flash
          </div>
        </div>

        <div className="mb-5 rounded-xl border border-slate-100 bg-slate-50/70 p-4">
          <p className="mb-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">
            Timing Ruleset
          </p>
          <div className="flex flex-wrap gap-4">
            {(
              [
                "Medicare 8-Minute Rule",
                "AMA Rule of Eight",
              ] as TimingRuleset[]
            ).map((option) => (
              <label
                key={option}
                className="inline-flex cursor-pointer items-center gap-2 text-sm font-medium text-slate-700"
              >
                <input
                  type="radio"
                  name="timing-ruleset"
                  value={option}
                  checked={ruleset === option}
                  onChange={() => setRuleset(option)}
                  className="h-4 w-4 border-slate-300 text-ast-blue focus:ring-ast-blue/30"
                />
                {option}
              </label>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          <div className="hidden grid-cols-[1.1fr_0.7fr_1.1fr_auto] gap-3 px-1 text-[10px] font-bold uppercase tracking-wider text-slate-400 md:grid">
            <span>CPT Code</span>
            <span>Duration (min)</span>
            <span>Body Region</span>
            <span className="w-8" />
          </div>

          {rows.map((row, index) => (
            <div
              key={row.id}
              className="grid grid-cols-1 gap-3 rounded-xl border border-slate-200/80 bg-white p-3 shadow-[0_1px_2px_rgba(0,0,0,0.02)] md:grid-cols-[1.1fr_0.7fr_1.1fr_auto] md:items-end md:border-0 md:bg-transparent md:p-0 md:shadow-none"
            >
              <label className="block">
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400 md:hidden">
                  CPT Code
                </span>
                <input
                  list={`cpt-options-${row.id}`}
                  value={row.cptCode}
                  onChange={(event) =>
                    updateRow(row.id, { cptCode: event.target.value })
                  }
                  placeholder="e.g. 97110"
                  className="w-full rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2 text-sm font-mono text-slate-700 placeholder:text-slate-400 focus:border-ast-blue/40 focus:outline-none focus:ring-2 focus:ring-ast-blue/20"
                />
                <datalist id={`cpt-options-${row.id}`}>
                  {COMMON_CPT_CODES.map((code) => (
                    <option key={code} value={code} />
                  ))}
                </datalist>
              </label>

              <label className="block">
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400 md:hidden">
                  Duration (min)
                </span>
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={row.durationMinutes}
                  onChange={(event) =>
                    updateRow(row.id, {
                      durationMinutes: Number(event.target.value) || 0,
                    })
                  }
                  className="w-full rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2 text-sm text-slate-700 focus:border-ast-blue/40 focus:outline-none focus:ring-2 focus:ring-ast-blue/20"
                />
              </label>

              <label className="block">
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-400 md:hidden">
                  Body Region
                </span>
                <input
                  list={`region-options-${row.id}`}
                  value={row.bodyRegion}
                  onChange={(event) =>
                    updateRow(row.id, { bodyRegion: event.target.value })
                  }
                  placeholder="Shoulder, knee, spine..."
                  className="w-full rounded-lg border border-slate-200 bg-slate-50/50 px-3 py-2 text-sm text-slate-700 placeholder:text-slate-400 focus:border-ast-blue/40 focus:outline-none focus:ring-2 focus:ring-ast-blue/20"
                />
                <datalist id={`region-options-${row.id}`}>
                  {BODY_REGIONS.map((region) => (
                    <option key={region} value={region} />
                  ))}
                </datalist>
              </label>

              <button
                type="button"
                onClick={() => removeRow(row.id)}
                disabled={rows.length === 1}
                className="flex h-10 w-full items-center justify-center rounded-lg border border-slate-200 text-slate-400 transition-colors hover:border-red-200 hover:bg-red-50 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-40 md:w-10"
                aria-label={`Remove CPT row ${index + 1}`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>

        <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <button
            type="button"
            onClick={addRow}
            className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-slate-600 transition-colors hover:bg-slate-50"
          >
            + Add CPT Row
          </button>

          <button
            type="button"
            onClick={handleRunVerification}
            disabled={loading}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-ast-blue to-ast-dark-blue px-6 py-3 text-sm font-bold text-white shadow-lg shadow-ast-blue/25 transition-all hover:shadow-xl disabled:cursor-not-allowed disabled:opacity-70"
          >
            {loading ? (
              <>
                <Spinner />
                Auditing Compliance via Gemini...
              </>
            ) : (
              <>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z" />
                  <path d="m9 12 2 2 4-4" />
                </svg>
                Run LLM Verification
              </>
            )}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <EngineBaselinePanel
          result={engineResult}
          error={engineError}
          loading={loading && !engineResult && !engineError}
        />

        <LlmVerdictCard result={llmResult} error={llmError} loading={loading && !llmResult && !llmError} />
      </div>

      <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
        <div className="mb-4">
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
            Reconciliation
          </p>
          <h3 className="text-lg font-extrabold text-ast-navy">
            Side-by-Side Discrepancy Check
          </h3>
        </div>
        <DiscrepancyComparison
          rows={comparisonRows}
          engineTotal={engineResult?.totalUnits ?? null}
          llmTotal={llmResult?.total_billable_units ?? null}
          totalMismatch={totalMismatch}
        />

        {llmResult && (
          <div className="mt-4 rounded-xl border border-slate-100 bg-slate-50/70 p-4 text-sm text-slate-600">
            <p className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
              Auditor Notes
            </p>
            <p>{llmResult.auditor_notes}</p>
          </div>
        )}
      </div>
    </section>
  );
}

function LlmVerdictCard({
  result,
  error,
  loading,
}: {
  result: LlmAuditResponse | null;
  error: string | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Spinner />
          Auditing Compliance via Gemini...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 shadow-sm">
        <p className="font-semibold">Gemini audit failed</p>
        <p className="mt-1">{error}</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
        LLM auditor verdict will appear here after verification.
      </div>
    );
  }

  const passed = result.validation_status === "PASSED";

  return (
    <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
            Gemini Auditor
          </p>
          <h3 className="text-lg font-extrabold text-ast-navy">LLM Auditor Verdict</h3>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide ${
            passed
              ? "border border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border border-red-200 bg-red-50 text-red-700"
          }`}
        >
          {result.validation_status}
        </span>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-slate-100 bg-slate-50/80 px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Total Units
          </p>
          <p className="text-2xl font-extrabold text-ast-navy">
            {result.total_billable_units}
          </p>
        </div>
        <div className="rounded-xl border border-slate-100 bg-slate-50/80 px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Rule Applied
          </p>
          <p className="text-sm font-bold text-ast-navy">{result.rule_applied}</p>
        </div>
      </div>

      <div className="mb-3 rounded-xl border border-slate-100 bg-slate-50/80 px-4 py-3 text-sm">
        <span className="font-semibold text-slate-700">Modifier required: </span>
        <span className="font-mono font-bold text-ast-navy">
          {result.modifier_required ?? "None"}
        </span>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200/80">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50/90">
            <tr>
              <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Code
              </th>
              <th className="px-3 py-2.5 text-center text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Units
              </th>
              <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Explanation
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {result.calculated_codes.map((code) => (
              <tr key={code.cpt}>
                <td className="px-3 py-2.5 font-mono font-semibold text-ast-navy">
                  {code.cpt}
                </td>
                <td className="px-3 py-2.5 text-center font-semibold">{code.units}</td>
                <td className="px-3 py-2.5 text-xs leading-relaxed text-slate-600">
                  {code.explanation}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <svg
      className="h-5 w-5 animate-spin text-white"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}
