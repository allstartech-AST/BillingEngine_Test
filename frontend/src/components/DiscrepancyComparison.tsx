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
      <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/80 p-6 text-center text-sm text-slate-500">
        Run verification to compare local engine output against the Gemini auditor.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {totalMismatch && (
        <div className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <WarningIcon />
          <p>
            Total unit mismatch: local engine reports{" "}
            <strong>{engineTotal ?? "—"}</strong> units, Gemini auditor reports{" "}
            <strong>{llmTotal ?? "—"}</strong> units.
          </p>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200/80 bg-white shadow-sm">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50/90">
            <tr>
              <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-slate-500">
                CPT
              </th>
              <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Region
              </th>
              <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Engine Units
              </th>
              <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-wider text-slate-500">
                LLM Units
              </th>
              <th className="px-4 py-3 text-center text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Modifiers
              </th>
              <th className="px-4 py-3 text-left text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Status
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => {
              const hasMismatch = row.hasUnitMismatch || row.hasModifierMismatch;
              return (
                <tr
                  key={row.cpt}
                  className={hasMismatch ? "bg-red-50/80" : "bg-white"}
                >
                  <td className="px-4 py-3 font-mono font-semibold text-ast-navy">
                    {row.cpt}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{row.bodyRegion || "—"}</td>
                  <td className="px-4 py-3 text-center font-semibold text-ast-navy">
                    {row.engineUnits ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-center font-semibold text-ast-navy">
                    {row.llmUnits ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-center text-xs text-slate-600">
                    {row.engineModifiers.length > 0
                      ? row.engineModifiers.join(", ")
                      : row.llmModifierRequired
                        ? "59 (LLM)"
                        : "None"}
                  </td>
                  <td className="px-4 py-3">
                    {hasMismatch ? (
                      <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-600">
                        <WarningIcon />
                        Discrepancy
                      </span>
                    ) : (
                      <span className="text-xs font-semibold text-emerald-600">
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
