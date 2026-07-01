from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
