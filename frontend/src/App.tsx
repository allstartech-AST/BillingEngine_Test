import LLMValidationCalculator from "./components/LLMValidationCalculator";

export default function App() {
  return (
    <div className="min-h-screen bg-ast-bg">
      <header className="sticky top-0 z-20 flex h-16 items-center border-b border-slate-200 bg-white px-4 shadow-sm sm:px-6">
        <button
          type="button"
          className="flex-shrink-0 rounded-md p-1.5 transition-colors hover:bg-slate-100"
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
            className="text-slate-500"
            aria-hidden="true"
          >
            <path d="M4 5h16" />
            <path d="M4 12h16" />
            <path d="M4 19h16" />
          </svg>
        </button>

        <div className="ml-2 text-xl font-extrabold tracking-tight">
          <span className="text-ast-navy">Medexa</span>
          <span className="text-ast-blue">.</span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span className="hidden rounded-full border border-ast-blue/10 bg-ast-tint px-3 py-1 text-[10px] font-bold uppercase tracking-wide text-ast-blue sm:inline-flex">
            Billing Intelligence
          </span>
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-ast-blue to-ast-dark-blue text-[10px] font-bold text-white ring-2 ring-slate-200">
            SM
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-6 rounded-2xl border border-slate-200/60 bg-white px-6 py-5 shadow-sm">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-400">
            Compliance Validation Lab
          </p>
          <h1 className="text-2xl font-extrabold tracking-tight text-ast-navy sm:text-3xl">
            Billing Engine vs.{" "}
            <span className="text-ast-blue">LLM Auditor</span>
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-500">
            Enter CPT scenarios manually, run the local billing engine baseline, and
            cross-check results with an independent Gemini compliance audit.
          </p>
        </div>

        <LLMValidationCalculator />
      </main>
    </div>
  );
}
