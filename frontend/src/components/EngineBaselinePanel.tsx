import type { EngineBaselineResult } from "../types/audit";

interface EngineBaselinePanelProps {
  result: EngineBaselineResult | null;
  error: string | null;
  loading: boolean;
}

export default function EngineBaselinePanel({
  result,
  error,
  loading,
}: EngineBaselinePanelProps) {
  if (loading) {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center rounded-2xl border border-slate-200/60 bg-white p-6 shadow-sm">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Spinner />
          Running local billing engine...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 shadow-sm">
        <p className="font-semibold">Engine evaluation failed</p>
        <p className="mt-1">{error}</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
        Local engine baseline will appear here after verification.
      </div>
    );
  }

  const ruleLabel =
    result.billingRule === "ama_rule_of_8"
      ? "AMA Rule of 8"
      : "Medicare 8-Minute Rule";

  return (
    <div className="rounded-2xl border border-slate-200/60 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
            Local Billing Engine
          </p>
          <h3 className="text-lg font-extrabold text-ast-navy">Baseline Calculation</h3>
        </div>
        <span className="rounded-full border border-ast-blue/10 bg-ast-tint px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-ast-blue">
          {ruleLabel}
        </span>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-slate-100 bg-slate-50/80 px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Total Units
          </p>
          <p className="text-2xl font-extrabold text-ast-navy">{result.totalUnits}</p>
        </div>
        <div className="rounded-xl border border-slate-100 bg-slate-50/80 px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
            Modifier Signal
          </p>
          <p className="text-lg font-bold text-ast-navy">
            {result.modifierSuggested ?? result.codes.find((c) => c.modifiers.length)?.modifiers.join(", ") ?? "None"}
          </p>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200/80">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50/90">
            <tr>
              <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Code
              </th>
              <th className="px-3 py-2.5 text-left text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Description
              </th>
              <th className="px-3 py-2.5 text-center text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Units
              </th>
              <th className="px-3 py-2.5 text-center text-[10px] font-bold uppercase tracking-wider text-slate-500">
                Duration
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {result.codes.map((code) => (
              <tr key={code.cpt}>
                <td className="px-3 py-2.5 font-mono font-semibold text-ast-navy">
                  {code.cpt}
                </td>
                <td className="px-3 py-2.5 text-slate-600">{code.description}</td>
                <td className="px-3 py-2.5 text-center font-semibold">{code.units}</td>
                <td className="px-3 py-2.5 text-center text-slate-600">
                  {Math.round(code.durationMinutes)} min
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
      className="h-5 w-5 animate-spin text-ast-blue"
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
