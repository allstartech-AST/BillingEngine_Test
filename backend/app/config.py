from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env_files() -> None:
    """Load .env then .env.local from the backend root (.env.local wins)."""
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.local", override=True)


def openai_api_key() -> str | None:
    import os

    load_env_files()
    return os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY")


def openai_model() -> str:
    import os

    load_env_files()
    return (
        os.environ.get("GROQ_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or "llama-3.1-8b-instant"
    )


def llm_provider_name() -> str:
    import os

    load_env_files()
    return "Groq" if os.environ.get("GROQ_API_KEY") else "OpenAI"


def groq_base_url() -> str:
    import os

    load_env_files()
    return os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")


def _env_int(name: str, default: int) -> int:
    import os

    load_env_files()
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    import os

    load_env_files()
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# Live AI enrichment cadence and suggest-missing transcript caps (Phase 1).
LLM_SENTENCES_PER_AI_BATCH = _env_int("LLM_SENTENCES_PER_AI_BATCH", 40)
LLM_SUGGEST_CONTEXT_CHARS = _env_int("LLM_SUGGEST_CONTEXT_CHARS", 200)
LLM_SUGGEST_MIN_DELTA_CHARS = _env_int("LLM_SUGGEST_MIN_DELTA_CHARS", 150)
LLM_SUGGEST_MAX_DELTA_CHARS = _env_int("LLM_SUGGEST_MAX_DELTA_CHARS", 3000)

# Live AI enrichment scheduling (Phase 5 — debounce + skip-if-busy).
LLM_ENRICHMENT_DEBOUNCE_SECONDS = _env_float("LLM_ENRICHMENT_DEBOUNCE_SECONDS", 2.0)

# Minimum seconds between consecutive LLM HTTP requests (gap after each completes).
LLM_REQUEST_INTERVAL_SECONDS = _env_float("LLM_REQUEST_INTERVAL_SECONDS", 3.0)

# Groq free-tier TPM (~6000/min) needs wider spacing for large billing prompts.
LLM_GROQ_MIN_INTERVAL_SECONDS = _env_float("LLM_GROQ_MIN_INTERVAL_SECONDS", 25.0)


DATA_DIR = PROJECT_ROOT / "data"
BILLING_DIR = DATA_DIR / "billing"
MEDEXA_DIR = DATA_DIR / "medexa"

BILLING_FILES = {
    "general": BILLING_DIR / "cpt_general_info.json",
    "icd10": BILLING_DIR / "cpt_icd10_info.json",
    "ptp": BILLING_DIR / "cpt_ptp_info.json",
    "mue": BILLING_DIR / "cpt_mue_info.json",
    "aoc": BILLING_DIR / "cpt_aoc_info.json",
    "categories": BILLING_DIR / "pt_ot_slp_billing_categories.json",
}

MEDEXA_FILE = MEDEXA_DIR / "medexa_cpt_lookup.json"
MEDEXA_ICD10_FILE = MEDEXA_DIR / "medexa_icd10_lookup.json"
ICD10_DESCRIPTIONS_FILE = BILLING_DIR / "icd10_descriptions.json"

ICD_ALTERNATIVES_CAP = 20
CONTEXT_WINDOW_TOKENS = 10

GLOBAL_TRANSCRIPT_EXCLUSIONS = [
    "recommended",
    "referral",
    "discussed",
    "considering",
]

WORD_BOUNDARY_PHRASES = {
    "tens", "mfr", "fce", "at eval", "at evaluation",
    "massage", "group session", "lsvt", "nmes", "lllt",
    "iastm", "ther ex", "ther act",
}

MODIFIERS = ["59", "XE", "XP", "XS", "XU"]

PENDING_UNITS_MESSAGE = (
    "Units calculated but awaiting therapist confirmation — bypassable NCCI bundling conflict."
)

PENDING_ICD_MESSAGE = (
    "Units calculated but awaiting therapist confirmation — ICD medical necessity review."
)

PENDING_REVIEW_MESSAGE = (
    "Units calculated but awaiting therapist confirmation."
)
