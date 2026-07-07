import LLMValidationCalculator from "./components/LLMValidationCalculator";

export default function App() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 via-slate-950 to-slate-900 text-slate-100">
      <header className="sticky top-0 z-20 border-b border-white/5 bg-slate-950/80 px-4 backdrop-blur-sm sm:px-6">
        <div className="mx-auto flex h-16 w-full max-w-[1400px] items-center">
        <button
          type="button"
          className="flex-shrink-0 rounded-lg p-1.5 text-slate-400 ring-1 ring-transparent transition hover:bg-slate-900/80 hover:text-slate-100 hover:ring-slate-700/60"
          aria-label="Menu"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-inherit"
            aria-hidden="true"
          >
            <path d="M4 5h16" />
            <path d="M4 12h16" />
            <path d="M4 19h16" />
          </svg>
        </button>

        <div className="ml-3 flex items-center gap-2 text-xl font-extrabold tracking-tight">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-ast-blue to-ast-dark-blue text-[13px] text-white shadow-sm shadow-ast-blue/40">
            M
          </span>
          <div>
            <span className="bg-gradient-to-r from-slate-50 to-slate-300 bg-clip-text text-transparent">
              Medexa
            </span>
            <span className="text-ast-blue">.</span>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="hidden items-center gap-2 rounded-full border border-ast-blue/20 bg-ast-tint/20 px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-300 sm:inline-flex">
            <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-emerald-500 text-[8px] text-black shadow-sm shadow-emerald-500/40" />
            Billing Intelligence Lab
          </span>
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-ast-blue to-ast-dark-blue text-[10px] font-bold text-white ring-2 ring-slate-900">
            SM
          </div>
        </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1400px] px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8 grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          <div className="relative overflow-hidden rounded-2xl border border-white/5 bg-gradient-to-br from-slate-950 via-slate-950 to-slate-900 px-6 py-5 shadow-[0_18px_40px_rgba(15,23,42,0.75)]">
            <div className="pointer-events-none absolute inset-px rounded-[18px] border border-white/5/10" />
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">
              Compliance Validation Lab
            </p>
            <h1 className="text-2xl font-extrabold tracking-tight text-slate-50 sm:text-3xl">
              Billing Engine vs.{" "}
              <span className="bg-gradient-to-r from-ast-blue via-sky-400 to-indigo-400 bg-clip-text text-transparent">
                LLM Auditor
              </span>
            </h1>
            <p className="mt-3 max-w-3xl text-sm text-slate-400">
              Enter CPT scenarios, run the local billing engine baseline, and reconcile
              results against an independent OpenAI-powered compliance auditor — all in
              one focused workspace.
            </p>
          </div>
          <div className="relative overflow-hidden rounded-2xl border border-ast-blue/30 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-5 shadow-[0_18px_40px_rgba(37,99,235,0.55)]">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.3),transparent_55%),radial-gradient(circle_at_bottom_right,rgba(56,189,248,0.2),transparent_55%)]" />
            <div className="relative flex h-full flex-col justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-300">
                  Live Comparison
                </p>
                <p className="mt-2 text-sm text-slate-200">
                  See billing math and LLM auditing decisions side-by-side, with unit
                  mismatches and modifier recommendations surfaced instantly.
                </p>
              </div>
              <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-900/70 px-3 py-1 text-slate-200 ring-1 ring-white/10">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                  Engine Baseline
                </span>
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-900/70 px-3 py-1 text-slate-200 ring-1 ring-white/10">
                  <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />
                  LLM Verdict
                </span>
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-900/70 px-3 py-1 text-slate-200 ring-1 ring-white/10">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                  Discrepancy Alerts
                </span>
              </div>
            </div>
          </div>
        </div>

        <LLMValidationCalculator />
      </main>
    </div>
  );
}
