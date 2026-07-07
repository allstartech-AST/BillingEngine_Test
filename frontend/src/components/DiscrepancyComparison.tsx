import type { ComparisonRow } from "../types/audit";

interface DiscrepancyComparisonProps {
  rows: ComparisonRow[];
  engineTotal: number | null;
  llmTotal: number | null;
  totalMismatch: boolean;
}

function WarningIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4 text-red-500 flex-shrink-0"
      aria-hidden="true"
    >
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

export default function DiscrepancyComparison({
  rows,
  engineTotal,
  llmTotal,
  totalMismatch,
}: DiscrepancyComparisonProps) {
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-700 bg-slate-950/80 p-6 text-center text-sm text-slate-400">
        Run verification to compare local engine output against the OpenAI auditor.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {totalMismatch && (
        <div className="flex items-start gap-2 rounded-xl border border-red-500/50 bg-red-950/60 px-4 py-3 text-sm text-red-100 shadow-[0_10px_30px_rgba(127,29,29,0.7)]">
          <WarningIcon />
          <p>
            Total unit mismatch: local engine reports{" "}
            <strong>{engineTotal ?? "—"}</strong> units, OpenAI auditor reports{" "}
            <strong>{llmTotal ?? "—"}</strong> units.
          </p>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-800/80 bg-slate-950/70 shadow-[0_18px_40px_rgba(15,23,42,0.85)]">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-950/90">
            <tr>
              <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                CPT
              </th>
              <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Region
              </th>
              <th className="px-4 py-3 text-center text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Engine Units
              </th>
              <th className="px-4 py-3 text-center text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                LLM Units
              </th>
              <th className="px-4 py-3 text-center text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Modifiers
              </th>
              <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.map((row) => {
              const hasMismatch = row.hasUnitMismatch || row.hasModifierMismatch;
              return (
                <tr
                  key={row.cpt}
                  className={
                    hasMismatch
                      ? "bg-red-950/50"
                      : "bg-gradient-to-r from-slate-950 via-slate-950 to-slate-950"
                  }
                >
                  <td className="px-4 py-3 font-mono font-semibold text-slate-50">
                    {row.cpt}
                  </td>
                  <td className="px-4 py-3 text-ast-text-muted">
                    {row.bodyRegion || "—"}
                  </td>
                  <td className="px-4 py-3 text-center font-semibold text-slate-50">
                    {row.engineUnits ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-center font-semibold text-slate-50">
                    {row.llmUnits ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-center text-xs text-ast-text-muted">
                    {row.engineModifiers.length > 0
                      ? row.engineModifiers.join(", ")
                      : row.llmModifierRequired
                        ? "59 (LLM)"
                        : "None"}
                  </td>
                  <td className="px-4 py-3">
                    {hasMismatch ? (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1 text-xs font-semibold text-red-300 ring-1 ring-red-500/40">
                        <WarningIcon />
                        Discrepancy
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-300 ring-1 ring-emerald-500/40">
                        Matched
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function buildComparisonRows(
  engineCodes: Array<{
    cpt: string;
    units: number;
    modifiers: string[];
    bodyRegion: string;
  }>,
  llmCodes: Array<{ cpt: string; units: number; explanation: string }>,
  llmModifierRequired: "59" | null,
  engineModifierSuggested: string | null,
  regionMap: Map<string, string>,
): ComparisonRow[] {
  const allCpts = new Set([
    ...engineCodes.map((c) => c.cpt),
    ...llmCodes.map((c) => c.cpt),
  ]);

  const engineMap = new Map(engineCodes.map((c) => [c.cpt, c]));
  const llmMap = new Map(llmCodes.map((c) => [c.cpt, c]));

  const engineHas59 =
    engineCodes.some((c) => c.modifiers.includes("59")) ||
    engineModifierSuggested === "59";
  const llmHas59 = llmModifierRequired === "59";
  const sessionModifierMismatch = engineHas59 !== llmHas59;

  return Array.from(allCpts).map((cpt) => {
    const engine = engineMap.get(cpt);
    const llm = llmMap.get(cpt);
    const hasUnitMismatch =
      engine != null && llm != null && engine.units !== llm.units;
    const hasModifierMismatch = sessionModifierMismatch;

    return {
      cpt,
      engineUnits: engine?.units ?? null,
      llmUnits: llm?.units ?? null,
      engineModifiers: engine?.modifiers ?? [],
      llmModifierRequired: llmHas59,
      hasUnitMismatch,
      hasModifierMismatch,
      llmExplanation: llm?.explanation ?? null,
      bodyRegion: regionMap.get(cpt) ?? engine?.bodyRegion ?? "",
    };
  });
}
