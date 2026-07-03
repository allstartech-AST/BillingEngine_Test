from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_env_files() -> None:
    """Load .env then .env.local from the backend root (.env.local wins)."""
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.local", override=True)


def gemini_api_key() -> str | None:
    import os

    load_env_files()
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("VITE_GEMINI_API_KEY")


def gemini_audit_model() -> str:
    import os

    load_env_files()
    return os.environ.get("GEMINI_AUDIT_MODEL", "gemini-2.5-flash")


DATA_DIR = PROJECT_ROOT / "data"
BILLING_DIR = DATA_DIR / "billing"
MEDEXA_DIR = DATA_DIR / "medexa"

BILLING_FILES = {
    "general": BILLING_DIR / "cpt_general_info.json",
    "icd10": BILLING_DIR / "cpt_icd10_info.json",
    "ptp": BILLING_DIR / "cpt_ptp_info.json",
    "mue": BILLING_DIR / "cpt_mue_info.json",
    "aoc": BILLING_DIR / "cpt_aoc_info.json",
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
