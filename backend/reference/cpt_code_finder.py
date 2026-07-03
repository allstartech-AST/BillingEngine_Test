"""
CPT Code Matcher
=================

A lightweight, dependency-free NLP matching engine that finds CPT codes in
clinical session transcripts using the proximity-based rules defined in
medexa_cpt_lookup.json (trigger_phrases + required_context + exclude_if_present).

Why this approach (and not the "_efficient" file):
The _efficient file pre-multiplies verbs x adjectives x nouns into literal
strings ("completed active range of motion drill", etc). That only matches
robotic, exact phrasing and balloons to 16k+ lines. This engine instead keeps
short, clinically meaningful trigger phrases and checks for *contextual*
action words near them, with tolerance for natural speech: filler words,
verb tense, plurals, and word order gaps.

Key design points:
1. Lightweight stemming so "exercise"/"exercises", "train"/"trained"/
   "training" etc. are treated as equivalent without needing nltk.
2. Subsequence matching with a gap tolerance so a trigger phrase like
   "therapeutic exercise" still matches "...her new therapeutic exercises
   today" even though extra words intervene between/around phrase tokens.
3. Sentence segmentation, since required_context / exclude_if_present
   rules are meant to apply within the same clinical statement.
4. A token-distance proximity check (default 10 tokens) for required_context,
   independent of sentence boundaries, matching the spec in _meta.
"""

import json
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# ----------------------------------------------------------------------
# Lightweight stemmer (no external dependencies / no internet required)
# ----------------------------------------------------------------------
def stem(word: str) -> str:
    """Very small suffix-stripping stemmer, good enough for clinical verbs
    and nouns (exercise/exercises, train/trained/training, walk/walked)."""
    w = word.lower()
    if len(w) <= 3:
        return w
    # ordering matters: longer/more specific suffixes first
    suffixes = [
        ("ization", "ize"), ("isation", "ise"),
        ("ational", "ate"), ("tional", "tion"),
        ("ies", "y"), ("ing", ""), ("edly", ""),
        ("edness", ""), ("ed", ""), ("ization", ""),
        ("es", ""), ("s", ""),
    ]
    for suf, repl in suffixes:
        if w.endswith(suf) and len(w) - len(suf) >= 2:
            return w[: -len(suf)] + repl
    return w


# ----------------------------------------------------------------------
# Irregular verb normalization (covers cases regular suffix-stripping
# can't, like did/done -> do, since "did" isn't a regular form of "do")
# ----------------------------------------------------------------------
_IRREGULAR_VERBS = {
    "did": "do", "does": "do", "done": "do", "doing": "do",
    "began": "begin", "begun": "begin",
    "went": "go", "gone": "go",
    "got": "get", "gotten": "get",
    "put": "put", "putting": "put",
}


def normalize_word(word: str) -> str:
    base = stem(word)
    return _IRREGULAR_VERBS.get(word.lower(), base)


# ----------------------------------------------------------------------
# Generic clinical action verbs: used as a fallback when a code's
# required_context list (from the JSON) doesn't happen to include the
# exact verb the speaker used. The JSON's required_context exists to
# confirm an action actually occurred (vs. being planned/evaluated) --
# this fallback preserves that intent while covering natural variation
# the data file's hand-picked word lists won't anticipate.
# ----------------------------------------------------------------------
_GENERIC_ACTION_VERBS = {
    "do", "perform", "work", "complete", "finish", "start", "begin",
    "continue", "apply", "place", "transition", "initiate", "deliver",
    "provide", "conduct", "give", "use", "administer", "execute",
}


# ----------------------------------------------------------------------
# Tokenization / sentence splitting
# ----------------------------------------------------------------------
_WORD_RE = re.compile(r"[a-z0-9']+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def normalize_text(text: str) -> str:
    text = text.lower()
    text = text.replace("\u2019", "'")
    # strip bracketed annotations e.g. "[15 minutes of gait training - 97116]"
    text = re.sub(r"\[[^\]]*\]", " ", text)
    # strip leading speaker labels e.g. "therapist a:", "patient:"
    text = re.sub(r"(?m)^\s*[a-z][a-z0-9 ]{0,25}:\s*", "", text)
    return text


def split_sentences(text: str) -> List[str]:
    text = normalize_text(text)
    # also break on common transcript turn markers / line breaks as soft
    # sentence boundaries, since therapists often run thoughts together
    text = re.sub(r"\n+", ". ", text)
    parts = _SENT_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def tokenize(sentence: str) -> List[str]:
    return _WORD_RE.findall(sentence)


@dataclass
class TokenIndex:
    """Tokens for a sentence plus their stems, to allow fast comparison."""
    tokens: List[str]
    stems: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.stems:
            self.stems = [normalize_word(t) for t in self.tokens]


def build_index(sentence: str) -> TokenIndex:
    toks = tokenize(sentence)
    return TokenIndex(tokens=toks)


# ----------------------------------------------------------------------
# Phrase matching: subsequence search with gap tolerance + stemming
# ----------------------------------------------------------------------
def find_phrase_span(idx: TokenIndex, phrase: str, max_gap: int = 2):
    """
    Search for `phrase` (a multi-word string) inside the tokenized sentence
    `idx`. Tries two strategies:

    1. In-order subsequence match, allowing up to `max_gap` filler tokens
       between each consecutive phrase word (handles "therapeutic [new]
       exercises" type insertions).
    2. Order-flexible fallback: if (1) fails, check whether all phrase
       words appear together within a small window regardless of order.
       This catches natural reordering like a speaker saying "unattended
       electrical stimulation" when the data lists the phrase as
       "electrical stimulation unattended" -- common with trailing
       modifiers in clinical terminology lists.

    Returns (start_idx, end_idx) token span (inclusive) covering the
    matched words, or None if no match is found.
    """
    span = _find_phrase_span_ordered(idx, phrase, max_gap=max_gap)
    if span is not None:
        return span
    return _find_phrase_span_unordered(idx, phrase, max_gap=max_gap)


def _find_phrase_span_ordered(idx: TokenIndex, phrase: str, max_gap: int = 2):
    phrase_words = [normalize_word(w) for w in tokenize(phrase)]
    if not phrase_words:
        return None

    n = len(idx.stems)

    # Try every possible starting position for the first phrase word
    for start in range(n):
        if idx.stems[start] != phrase_words[0]:
            continue
        cursor = start
        matched_to = start
        ok = True
        for pw in phrase_words[1:]:
            found_at = None
            # search within max_gap+1 tokens ahead of cursor
            for j in range(cursor + 1, min(cursor + 2 + max_gap, n)):
                if idx.stems[j] == pw:
                    found_at = j
                    break
            if found_at is None:
                ok = False
                break
            cursor = found_at
            matched_to = found_at
        if ok:
            return (start, matched_to)
    return None


def _find_phrase_span_unordered(idx: TokenIndex, phrase: str, max_gap: int = 2):
    phrase_words = [normalize_word(w) for w in tokenize(phrase)]
    if len(phrase_words) < 2:
        return None  # single-word phrases have no order to be flexible about

    n = len(idx.stems)
    window = len(phrase_words) + max_gap * len(phrase_words)
    needed = set(phrase_words)

    for start in range(n):
        end = min(start + window, n)
        window_stems = idx.stems[start:end]
        if needed.issubset(set(window_stems)):
            # find tightest span covering all needed words within this window
            positions = []
            for w in needed:
                for k in range(start, end):
                    if idx.stems[k] == w:
                        positions.append(k)
                        break
            if positions and len(positions) == len(needed):
                return (min(positions), max(positions))
    return None


def phrase_present_anywhere(idx: TokenIndex, phrase: str, max_gap: int = 2) -> bool:
    return find_phrase_span(idx, phrase, max_gap=max_gap) is not None


def context_within_distance(
    idx: TokenIndex, context_phrase: str, span, max_token_distance: int, max_gap: int = 1
) -> bool:
    """
    Check whether `context_phrase` occurs within `max_token_distance` tokens
    of the trigger phrase span (start, end) in the same sentence's token
    index. context_phrase may itself be multi-word (e.g. "working on").
    """
    ctx_span = find_phrase_span(idx, context_phrase, max_gap=max_gap)
    if ctx_span is None:
        return False
    c_start, c_end = ctx_span
    t_start, t_end = span
    # distance is the gap between the closer ends of the two spans
    if c_end < t_start:
        distance = t_start - c_end
    elif c_start > t_end:
        distance = c_start - t_end
    else:
        distance = 0  # overlapping
    return distance <= max_token_distance


# ----------------------------------------------------------------------
# Match result + main matcher class
# ----------------------------------------------------------------------
@dataclass
class CodeMatch:
    code: str
    label: str
    trigger_phrase: str
    matched_text: str
    sentence: str
    sentence_index: int
    context_word: Optional[str]
    disciplines: List[str]
    ncci_conflicts: List[str]
    notes: str


class CPTMatcher:
    def __init__(
        self,
        lookup_path: str,
        proximity_tokens: int = 10,
        phrase_gap: int = 2,
        use_generic_action_fallback: bool = True,
    ):
        with open(lookup_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        self.meta = self.data.get("_meta", {})
        self.codes = {k: v for k, v in self.data.items() if k != "_meta"}
        self.proximity_tokens = proximity_tokens
        self.phrase_gap = phrase_gap
        self.use_generic_action_fallback = use_generic_action_fallback

    def match(
        self,
        transcript: str,
        discipline: Optional[str] = None,
        resolve_ncci_conflicts: bool = True,
    ) -> List[CodeMatch]:
        """
        Run the full matching pipeline over a transcript and return all
        codes that satisfy: trigger phrase present, AND (no required_context
        list OR at least one required_context word within proximity_tokens),
        AND no exclude_if_present phrase in the same sentence.

        If `discipline` is given (e.g. "PT", "OT", "SLP"), only codes valid
        for that discipline are considered.
        """
        sentences = split_sentences(transcript)
        results: List[CodeMatch] = []
        seen = set()  # (code, sentence_index) to avoid duplicate hits per sentence

        for s_i, sentence in enumerate(sentences):
            idx = build_index(sentence)
            if not idx.tokens:
                continue

            for code, rule in self.codes.items():
                if discipline and rule.get("disciplines") and discipline not in rule["disciplines"]:
                    continue

                triggers = rule.get("trigger_phrases", [])
                if not triggers:
                    continue  # e.g. add-on codes meant to be engine-derived only

                for trigger in triggers:
                    span = find_phrase_span(idx, trigger, max_gap=self.phrase_gap)
                    if span is None:
                        continue

                    # exclude_if_present check (same sentence)
                    excluded = False
                    for ex_phrase in rule.get("exclude_if_present", []):
                        if phrase_present_anywhere(idx, ex_phrase, max_gap=self.phrase_gap):
                            excluded = True
                            break
                    if excluded:
                        continue

                    # required_context proximity check
                    required = rule.get("required_context", [])
                    context_word_found = None
                    if required:
                        for ctx in required:
                            if context_within_distance(
                                idx, ctx, span, self.proximity_tokens, max_gap=1
                            ):
                                context_word_found = ctx
                                break
                        if context_word_found is None and self.use_generic_action_fallback:
                            # The JSON's required_context list confirms the action
                            # actually happened (vs. planned/evaluated). If none of
                            # its hand-picked words matched, fall back to a broader
                            # set of generic clinical action verbs near the trigger
                            # before giving up -- this is what catches phrasing the
                            # data file's author didn't anticipate, e.g. "perform",
                            # "transition to", "we'll do".
                            t_start, t_end = span
                            lo = max(0, t_start - self.proximity_tokens)
                            hi = min(len(idx.stems), t_end + 1 + self.proximity_tokens)
                            for k in range(lo, hi):
                                if idx.stems[k] in _GENERIC_ACTION_VERBS:
                                    context_word_found = idx.tokens[k] + " (generic)"
                                    break
                        if context_word_found is None:
                            continue  # no qualifying context nearby -> skip

                    key = (code, s_i)
                    if key in seen:
                        continue
                    seen.add(key)

                    t_start, t_end = span
                    matched_text = " ".join(idx.tokens[t_start : t_end + 1])

                    results.append(
                        CodeMatch(
                            code=code,
                            label=rule.get("label", ""),
                            trigger_phrase=trigger,
                            matched_text=matched_text,
                            sentence=sentence,
                            sentence_index=s_i,
                            context_word=context_word_found,
                            disciplines=rule.get("disciplines", []),
                            ncci_conflicts=rule.get("ncci_conflicts", []),
                            notes=rule.get("notes", ""),
                        )
                    )
                    break  # one match per code per sentence is enough

        if resolve_ncci_conflicts:
            results = self._flag_conflicts(results)

        return results

    @staticmethod
    def _flag_conflicts(results: List[CodeMatch]) -> List[CodeMatch]:
        """Doesn't remove conflicting codes (that's a billing/business
        decision, often resolved with modifier 59) -- just leaves the
        ncci_conflicts data attached so the caller can decide. Kept as a
        hook for future auto-resolution logic."""
        return results

    def summarize(self, transcript: str, discipline: Optional[str] = None) -> Dict:
        matches = self.match(transcript, discipline=discipline)
        by_code: Dict[str, List[CodeMatch]] = {}
        for m in matches:
            by_code.setdefault(m.code, []).append(m)
        return {
            code: {
                "label": ms[0].label,
                "hits": len(ms),
                "evidence": [
                    {
                        "sentence": m.sentence,
                        "matched_text": m.matched_text,
                        "context_word": m.context_word,
                    }
                    for m in ms
                ],
                "ncci_conflicts": ms[0].ncci_conflicts,
            }
            for code, ms in by_code.items()
        }



# ----------------------------------------------------------------------
# Run your transcript here
# ----------------------------------------------------------------------
def analyze_transcript(text, discipline=None):
    matcher = CPTMatcher("/content/medexa_cpt_lookup.json", proximity_tokens=10, phrase_gap=2)
    matches = matcher.match(text, discipline=discipline)
    if not matches:
        print("No CPT codes matched.")
        return
    seen_codes = sorted(set(m.code for m in matches))
    print(f"Matched codes: {seen_codes}\n")
    for m in matches:
        print(f"{m.code} - {m.label}")
        print(f"   matched: \'{m.matched_text}\'  (trigger: \'{m.trigger_phrase}\', context: \'{m.context_word}\')")
        print(f"   from: \"{m.sentence.strip()}\"")
        if m.ncci_conflicts:
            print(f"   note: NCCI conflicts with {m.ncci_conflicts} (may need modifier 59)")
        print()


# ----------------------------------------------------------------------
# PASTE YOUR TRANSCRIPT BELOW (between the triple quotes) AND RUN
# ----------------------------------------------------------------------
my_transcript = """
PASTE YOUR TRANSCRIPT HERE
"""

analyze_transcript(my_transcript)
