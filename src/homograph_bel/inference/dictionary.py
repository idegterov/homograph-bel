"""Fast dictionary scanning and constrained LLM prompt preparation."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from homograph_bel.dictionary.index import DictionaryIndex, normalize_lookup
from homograph_bel.dictionary.morphology import (
    MORPHOLOGY_DECODER_VERSION,
    DecodedGrammarDBAnalysis,
    decode_grammar_db_analysis,
)
from homograph_bel.dictionary.v2 import (
    BELARUSIAN_VOWELS,
    STRESS_MARKERS,
    DictionaryHomograph,
    DictionaryStatus,
)

PROMPT_VERSION = "homograph-adjudication-v1"
LEAN_PROMPT_VERSION = "homograph-lean-choice-v1"
LEAN_SYSTEM_PROMPT = (
    "Выберы правільны націск для <t>...</t>. "
    "Адкажы толькі нумарам варыянта або ?."  # noqa: RUF001 - intentional Belarusian
)
WORD_PATTERN = re.compile(
    r"[^\W\d_](?:[^\W\d_]|[\u0300-\u036f+\u00b4])*"
    r"(?:[-'\u2019\u02bc][^\W\d_](?:[^\W\d_]|[\u0300-\u036f+\u00b4])*)*"
)


class PromptContractError(ValueError):
    """Raised when supplied prompt evidence violates the public contract."""


@dataclass(frozen=True, slots=True)
class HomographOccurrence:
    """One exact dictionary homograph occurrence in original text."""

    text: str
    target_start: int
    target_end: int
    target_surface: str
    target_normalized: str
    homograph: DictionaryHomograph

    def __post_init__(self) -> None:
        """Validate the exact-offset invariant."""

        if not 0 <= self.target_start < self.target_end <= len(self.text):
            raise ValueError("occurrence offsets must form a non-empty in-range span")
        if self.text[self.target_start : self.target_end] != self.target_surface:
            raise ValueError("occurrence offsets must select target_surface exactly")
        if normalize_lookup(self.target_surface) != self.target_normalized:
            raise ValueError("target_normalized must match the normalized target surface")
        if normalize_lookup(self.homograph.official_surface) != self.target_normalized:
            raise ValueError("target surface must belong to the supplied homograph")

    @property
    def homograph_id(self) -> str:
        """Return the stable dictionary homograph identifier."""

        return self.homograph.homograph_id

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        """Return the stable closed candidate identifiers in dictionary order."""

        return tuple(candidate.variant_id for candidate in self.homograph.candidates)

    @property
    def dictionary_version(self) -> str:
        """Return the pinned dictionary release."""

        return self.homograph.dictionary_version

    @property
    def status(self) -> DictionaryStatus:
        """Return the linguistic resolution status."""

        return self.homograph.status


@dataclass(frozen=True, slots=True)
class AdjudicationPrompt:
    """One deterministic versioned prompt ready for an LLM provider."""

    version: str
    prompt: str
    prompt_hash: str


@dataclass(frozen=True, slots=True)
class LeanAdjudicationPrompt:
    """Compact prompt plus the host-side closed candidate mapping."""

    version: str
    system_prompt: str
    user_prompt: str
    prompt_hash: str
    decoder_version: str
    candidate_ids: tuple[str, ...]
    candidate_analyses: tuple[tuple[DecodedGrammarDBAnalysis, ...], ...]


class LeanResponseStatus(StrEnum):
    """Host validation status for a choice-only model response."""

    SELECTED = "selected"
    ABSTAINED = "abstained"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class LeanAdjudicationResult:
    """Validated host-side interpretation of a lean model response."""

    status: LeanResponseStatus
    selected_candidate_id: str | None
    possible_analyses: tuple[DecodedGrammarDBAnalysis, ...]
    raw_response: str


class HomographScanner:
    """Reusable Unicode token scanner backed by a preloaded hash index."""

    __slots__ = ("_index",)

    def __init__(self, index: DictionaryIndex) -> None:
        """Bind a scanner to one preloaded dictionary index."""

        self._index = index

    def scan(self, text: str) -> tuple[HomographOccurrence, ...]:
        """Return all whole-token dictionary matches in source order."""

        occurrences: list[HomographOccurrence] = []
        for match in WORD_PATTERN.finditer(text):
            surface = match.group()
            if not _has_valid_stress_markers(surface):
                continue
            normalized = normalize_lookup(surface)
            homograph = self._index.get_homograph(normalized)
            if homograph is not None:
                occurrences.append(
                    HomographOccurrence(
                        text=text,
                        target_start=match.start(),
                        target_end=match.end(),
                        target_surface=surface,
                        target_normalized=normalized,
                        homograph=homograph,
                    )
                )
        return tuple(occurrences)

    def scan_many(self, texts: Iterable[str]) -> Iterator[tuple[HomographOccurrence, ...]]:
        """Yield one result tuple per text without materializing the input corpus."""

        for text in texts:
            yield self.scan(text)


def build_adjudication_prompt(
    occurrence: HomographOccurrence,
    *,
    observed_morphology: Mapping[str, str] | None = None,
    examples: Sequence[str] = (),
) -> AdjudicationPrompt:
    """Render one deterministic prompt constrained to dictionary candidates."""

    morphology = _validate_morphology(observed_morphology)
    validated_examples = _validate_examples(examples)
    marked = (
        occurrence.text[: occurrence.target_start]
        + "<target>"
        + occurrence.target_surface
        + "</target>"
        + occurrence.text[occurrence.target_end :]
    )
    sections = [
        "Resolve the marked Belarusian homograph using only the closed candidate list.",
        f"Prompt version: {PROMPT_VERSION}",
        "",
        "Sentence:",
        occurrence.text,
        "",
        "Marked sentence:",
        marked,
        "",
        "Target:",
        (
            f"{occurrence.target_surface} "
            f"(characters {occurrence.target_start}:{occurrence.target_end}, "
            f"homograph_id={occurrence.homograph_id}, "
            f"dictionary_version={occurrence.dictionary_version}, "
            f"status={occurrence.status})"
        ),
        "",
        "Candidates (closed list):",
        _candidate_json(occurrence.homograph),
    ]
    if morphology is not None:
        sections.extend(("", "Observed morphology (caller supplied):", _compact_json(morphology)))
    if validated_examples:
        sections.extend(("", "Examples (caller supplied):", _compact_json(validated_examples)))
    sections.extend(
        (
            "",
            "Return exactly one JSON object with this schema:",
            _compact_json(
                {
                    "selected_candidate_id": "listed candidate ID or null",
                    "selected_lemma": "listed lemma or null",
                    "selected_pos": "listed POS or null",
                    "selected_morphology": ["listed morphology"],
                    "short_contextual_evidence": "brief evidence from the sentence",
                    "confidence": "high, medium, or low",
                    "ambiguous_or_insufficient": False,
                }
            ),
            "Use null candidate fields and ambiguous_or_insufficient=true when evidence is insufficient.",
            "Never invent a candidate, stress position, lemma, POS, morphology, or example.",
        )
    )
    prompt = "\n".join(sections)
    prompt_hash = hashlib.sha256(f"{PROMPT_VERSION}\0{prompt}".encode()).hexdigest()
    return AdjudicationPrompt(PROMPT_VERSION, prompt, prompt_hash)


def build_lean_adjudication_prompt(occurrence: HomographOccurrence) -> LeanAdjudicationPrompt:
    """Render a compact choice-only prompt with source-backed morphology."""

    marked = (
        occurrence.text[: occurrence.target_start]
        + "<t>"
        + occurrence.target_surface
        + "</t>"
        + occurrence.text[occurrence.target_end :]
    )
    candidate_ids: list[str] = []
    candidate_analyses: list[tuple[DecodedGrammarDBAnalysis, ...]] = []
    lines = [marked]
    for choice, candidate in enumerate(occurrence.homograph.candidates, start=1):
        decoded = _deduplicate_analyses(
            tuple(decode_grammar_db_analysis(item) for item in candidate.analyses)
        )
        candidate_ids.append(candidate.variant_id)
        candidate_analyses.append(decoded)
        evidence = _lean_candidate_text(decoded)
        suffix = f" | {evidence}" if evidence else ""
        lines.append(f"{choice} {candidate.official_stressed}{suffix}")
    user_prompt = "\n".join(lines)
    ids = tuple(candidate_ids)
    analyses = tuple(candidate_analyses)
    hash_payload = _compact_json(
        {
            "candidate_ids": ids,
            "decoder_version": MORPHOLOGY_DECODER_VERSION,
            "system_prompt": LEAN_SYSTEM_PROMPT,
            "user_prompt": user_prompt,
            "version": LEAN_PROMPT_VERSION,
        }
    )
    prompt_hash = hashlib.sha256(hash_payload.encode()).hexdigest()
    return LeanAdjudicationPrompt(
        LEAN_PROMPT_VERSION,
        LEAN_SYSTEM_PROMPT,
        user_prompt,
        prompt_hash,
        MORPHOLOGY_DECODER_VERSION,
        ids,
        analyses,
    )


def parse_lean_adjudication_response(
    prompt: LeanAdjudicationPrompt, response: str
) -> LeanAdjudicationResult:
    """Map one exact numbered choice or abstention to the stable dictionary contract."""

    stripped = response.strip()
    if stripped == "?":
        return LeanAdjudicationResult(LeanResponseStatus.ABSTAINED, None, (), response)
    if re.fullmatch(r"[1-9][0-9]*", stripped) is not None:
        index = int(stripped) - 1
        if index < len(prompt.candidate_ids):
            return LeanAdjudicationResult(
                LeanResponseStatus.SELECTED,
                prompt.candidate_ids[index],
                prompt.candidate_analyses[index],
                response,
            )
    return LeanAdjudicationResult(LeanResponseStatus.INVALID, None, (), response)


def _lean_candidate_text(analyses: tuple[DecodedGrammarDBAnalysis, ...]) -> str:
    grouped: dict[tuple[str, str, str | None], list[tuple[tuple[str, str], ...]]] = {}
    for analysis in analyses:
        key = (analysis.lemma, analysis.pos, analysis.meaning)
        grouped.setdefault(key, []).append(analysis.features)
    rendered: list[str] = []
    for (lemma, pos, meaning), forms in grouped.items():
        fields = [lemma, pos]
        if len(forms) == 1:
            fields.extend(f"{key}={value}" for key, value in forms[0])
        else:
            alternatives = " | ".join(
                ",".join(f"{key}={value}" for key, value in features) for features in forms
            )
            fields.append(f"Forms={alternatives}")
        if meaning is not None:
            fields.append(f"Meaning={meaning}")
        rendered.append("; ".join(field for field in fields if field))
    return " / ".join(rendered)


def _deduplicate_analyses(
    analyses: tuple[DecodedGrammarDBAnalysis, ...],
) -> tuple[DecodedGrammarDBAnalysis, ...]:
    unique: dict[
        tuple[str, str, tuple[tuple[str, str], ...], str | None], DecodedGrammarDBAnalysis
    ] = {}
    for analysis in analyses:
        key = (analysis.lemma, analysis.pos, analysis.features, analysis.meaning)
        unique.setdefault(key, analysis)
    return tuple(unique.values())


def _candidate_json(homograph: DictionaryHomograph) -> str:
    candidates = [
        {
            "candidate_id": candidate.variant_id,
            "stressed": candidate.official_stressed,
            "stress_position": candidate.stress_position,
            "status": candidate.status,
            "lifecycle_status": candidate.lifecycle_status,
            "provenance": list(candidate.provenance),
            "analyses": [
                {
                    "lemma": analysis.lemma,
                    "stressed_lemma": analysis.stressed_lemma,
                    "pos": analysis.pos,
                    "paradigm_tag": analysis.paradigm_tag,
                    "variant_tag": analysis.variant_tag,
                    "form_tag": analysis.form_tag,
                    "meaning": analysis.meaning,
                    "morphology": list(analysis.morphology),
                    "source_dictionaries": list(analysis.source_dictionaries),
                    "source_coordinates": analysis.provenance_id,
                }
                for analysis in candidate.analyses
            ],
        }
        for candidate in homograph.candidates
    ]
    return _compact_json(candidates)


def _validate_morphology(value: Mapping[str, str] | None) -> dict[str, str] | None:
    if value is None:
        return None
    if not value or any(
        not _is_nonempty_string(key) or not _is_nonempty_string(item) for key, item in value.items()
    ):
        raise PromptContractError("observed morphology must contain non-empty string pairs")
    return dict(sorted(value.items()))


def _validate_examples(value: Sequence[str]) -> tuple[str, ...]:
    if any(not _is_nonempty_string(item) for item in value):
        raise PromptContractError("examples must be non-empty strings")
    return tuple(value)


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_valid_stress_markers(value: str) -> bool:
    stresses = 0
    last_base = ""
    for character in unicodedata.normalize("NFD", value):
        if character in STRESS_MARKERS:
            stresses += 1
            if stresses > 1 or last_base.casefold() not in BELARUSIAN_VOWELS:
                return False
        elif character.isalpha():
            last_base = character
    return True


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "PROMPT_VERSION",
    "AdjudicationPrompt",
    "HomographOccurrence",
    "HomographScanner",
    "PromptContractError",
    "build_adjudication_prompt",
]
