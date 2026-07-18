"""Deterministic GrammarDB adjudication and exception-review contracts."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from homograph_bel.dictionary.v2 import (
    DictionaryCandidate,
    DictionaryHomograph,
    DictionaryStatus,
    DictionaryV2,
)

ADJUDICATION_SCHEMA_VERSION = "dictionary-adjudication-v1"
REVIEW_SCHEMA_VERSION = "dictionary-human-review-v1"
REVIEW_OUTPUT_SCHEMA_VERSION = "dictionary-review-output-v1"
REVIEW_DECISION_HEADERS = (
    "dictionary_version",
    "homograph_id",
    "official_surface",
    "decision",
    "review_status",
    "reviewer",
    "reviewed_at",
    "evidence",
    "reviewer_note",
    "review_schema_version",
)


class AdjudicationOutcome(StrEnum):
    """Whether automatic evidence is sufficient for a status decision."""

    AUTO_APPROVED = "auto_approved"
    NEEDS_FOLLOW_UP = "needs_follow_up"


class AdjudicationConfidence(StrEnum):
    """Confidence attached to a deterministic adjudication rule."""

    HIGH = "high"
    LOW = "low"


class HumanReviewStatus(StrEnum):
    """Lifecycle state of a reviewer-authored exception decision."""

    HUMAN_APPROVED = "human_approved"
    NEEDS_FOLLOW_UP = "needs_follow_up"


class ExceptionReviewState(StrEnum):
    """Human-review state shown in the generated exception queue."""

    PENDING = "pending"
    HUMAN_APPROVED = "human_approved"
    NEEDS_FOLLOW_UP = "needs_follow_up"


@dataclass(frozen=True, slots=True)
class CandidateReviewEvidence:
    """Normalized GrammarDB evidence used for one candidate decision."""

    variant_id: str
    official_stressed: str
    lifecycle_status: DictionaryStatus
    lemmas: tuple[str, ...]
    meanings: tuple[str, ...]
    parts_of_speech: tuple[str, ...]
    lexical_signatures: tuple[tuple[str, str, str | None], ...]
    incomplete_lexical_provenance_ids: tuple[str, ...]
    grammatical_analyses: tuple[tuple[str, str, str, tuple[str, ...]], ...]
    provenance_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AutomaticAdjudication:
    """One explainable automatic conclusion or follow-up decision."""

    dictionary_version: str
    homograph_id: str
    official_surface: str
    current_status: DictionaryStatus
    proposed_status: DictionaryStatus | None
    outcome: AdjudicationOutcome
    confidence: AdjudicationConfidence
    rule_code: str
    candidate_ids: tuple[str, ...]
    provenance_ids: tuple[str, ...]
    evidence: tuple[CandidateReviewEvidence, ...]
    evidence_hash: str
    explanation: str
    adjudication_schema_version: str = ADJUDICATION_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class HumanReviewDecision:
    """One release-bound and stable-ID-bound human exception decision."""

    dictionary_version: str
    homograph_id: str
    official_surface: str
    decision: DictionaryStatus
    review_status: HumanReviewStatus
    reviewer: str
    reviewed_at: date
    evidence: str
    reviewer_note: str
    review_schema_version: str = REVIEW_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ExceptionQueueItem:
    """One automatic exception or QA sample prepared for inspection."""

    dictionary_version: str
    homograph_id: str
    official_surface: str
    reasons: tuple[str, ...]
    review_state: ExceptionReviewState
    adjudication: AutomaticAdjudication
    human_decision: HumanReviewDecision | None


def adjudicate_dictionary(dictionary: DictionaryV2) -> tuple[AutomaticAdjudication, ...]:
    """Adjudicate every homograph in canonical dictionary order."""

    return tuple(_adjudicate_homograph(item) for item in dictionary.homographs)


def load_human_review_decisions(
    path: Path,
    dictionary: DictionaryV2,
) -> tuple[HumanReviewDecision, ...]:
    """Load and cross-check the strict human review-decision CSV contract."""

    by_id = {item.homograph_id: item for item in dictionary.homographs}
    decisions: list[HumanReviewDecision] = []
    seen: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REVIEW_DECISION_HEADERS:
            raise ValueError("unexpected human review decision headers")
        for row_number, raw_row in enumerate(reader, start=2):
            if None in raw_row:
                raise ValueError(f"row {row_number}: unexpected columns")
            row = {header: raw_row.get(header) or "" for header in REVIEW_DECISION_HEADERS}
            blank = next((header for header, value in row.items() if not value.strip()), None)
            if blank is not None:
                raise ValueError(f"row {row_number}: blank required field {blank}")
            if row["review_schema_version"] != REVIEW_SCHEMA_VERSION:
                raise ValueError(f"row {row_number}: unknown review schema")
            if row["dictionary_version"] != dictionary.release:
                raise ValueError(f"row {row_number}: unknown dictionary release")
            homograph = by_id.get(row["homograph_id"])
            if homograph is None:
                raise ValueError(f"row {row_number}: unknown homograph ID")
            if row["official_surface"] != homograph.official_surface:
                raise ValueError(f"row {row_number}: surface does not match homograph ID")
            decision = _parse_decision(row["decision"], row_number)
            review_status = _parse_review_status(row["review_status"], row_number)
            try:
                reviewed_at = date.fromisoformat(row["reviewed_at"])
            except ValueError as error:
                raise ValueError(f"row {row_number}: invalid reviewed_at date") from error
            key = (row["dictionary_version"], row["homograph_id"])
            if key in seen:
                raise ValueError(f"row {row_number}: duplicate decision key")
            seen.add(key)
            decisions.append(
                HumanReviewDecision(
                    dictionary_version=row["dictionary_version"],
                    homograph_id=row["homograph_id"],
                    official_surface=row["official_surface"],
                    decision=decision,
                    review_status=review_status,
                    reviewer=row["reviewer"],
                    reviewed_at=reviewed_at,
                    evidence=row["evidence"],
                    reviewer_note=row["reviewer_note"],
                )
            )
    return tuple(sorted(decisions, key=lambda item: (item.dictionary_version, item.homograph_id)))


def select_status_overrides(
    dictionary: DictionaryV2,
    adjudications: tuple[AutomaticAdjudication, ...],
    human_decisions: tuple[HumanReviewDecision, ...] = (),
) -> dict[str, DictionaryStatus]:
    """Select safe status overrides with explicit human-decision precedence."""

    homographs = {item.homograph_id: item for item in dictionary.homographs}
    adjudication_ids = [item.homograph_id for item in adjudications]
    if len(adjudication_ids) != len(set(adjudication_ids)) or set(adjudication_ids) != set(
        homographs
    ):
        raise ValueError("automatic adjudications must cover every homograph exactly once")
    overrides: dict[str, DictionaryStatus] = {}
    for item in adjudications:
        homograph = homographs[item.homograph_id]
        _validate_adjudication(item, homograph)
        if item.outcome is AdjudicationOutcome.AUTO_APPROVED:
            assert item.proposed_status is not None
            overrides[homograph.official_surface] = item.proposed_status
    seen_human: set[str] = set()
    for decision in human_decisions:
        if decision.homograph_id in seen_human:
            raise ValueError("human decisions must contain unique homograph IDs")
        seen_human.add(decision.homograph_id)
        homograph = homographs.get(decision.homograph_id)
        if homograph is None:
            raise ValueError("human decision references an unknown homograph ID")
        if (
            decision.dictionary_version != homograph.dictionary_version
            or decision.official_surface != homograph.official_surface
        ):
            raise ValueError("human decision does not match the dictionary record")
        if decision.review_schema_version != REVIEW_SCHEMA_VERSION:
            raise ValueError("human decision uses an unknown review schema")
        if decision.decision not in {
            DictionaryStatus.CONTEXTUAL,
            DictionaryStatus.FREE_VARIANT,
            DictionaryStatus.CONFLICT,
        }:
            raise ValueError("human decision must use a linguistic status")
        if decision.review_status is HumanReviewStatus.HUMAN_APPROVED:
            overrides[homograph.official_surface] = decision.decision
        else:
            overrides.pop(homograph.official_surface, None)
    return overrides


def select_adjudication_qa_sample(
    adjudications: Sequence[AutomaticAdjudication],
    *,
    frequencies: Mapping[str, int],
    sample_size: int,
    seed: str,
) -> tuple[str, ...]:
    """Select a deterministic round-robin sample across status/frequency groups."""

    if sample_size < 0:
        raise ValueError("sample_size must be non-negative")
    groups: dict[tuple[str, str], list[AutomaticAdjudication]] = defaultdict(list)
    for item in adjudications:
        if item.outcome is not AdjudicationOutcome.AUTO_APPROVED:
            continue
        status = item.proposed_status.value if item.proposed_status is not None else "unknown"
        band = _frequency_band(frequencies.get(item.official_surface, 0))
        groups[(status, band)].append(item)
    for items in groups.values():
        items.sort(key=lambda item: _sample_score(seed, item.homograph_id))
    selected: list[str] = []
    ordered_groups = [groups[key] for key in sorted(groups)]
    while len(selected) < sample_size and any(ordered_groups):
        for items in ordered_groups:
            if items and len(selected) < sample_size:
                selected.append(items.pop(0).homograph_id)
    return tuple(selected)


def build_exception_queue(
    dictionary: DictionaryV2,
    adjudications: tuple[AutomaticAdjudication, ...],
    *,
    human_decisions: tuple[HumanReviewDecision, ...] = (),
    qa_homograph_ids: Sequence[str] = (),
) -> tuple[ExceptionQueueItem, ...]:
    """Join automatic exceptions, QA selections, and human review state."""

    select_status_overrides(dictionary, adjudications, human_decisions)
    adjudication_by_id = {item.homograph_id: item for item in adjudications}
    decisions_by_id = {item.homograph_id: item for item in human_decisions}
    qa_ids = set(qa_homograph_ids)
    unknown_qa_ids = qa_ids - set(adjudication_by_id)
    if unknown_qa_ids:
        raise ValueError(f"QA sample references unknown homograph IDs: {sorted(unknown_qa_ids)}")
    queue: list[ExceptionQueueItem] = []
    for homograph in dictionary.homographs:
        adjudication = adjudication_by_id[homograph.homograph_id]
        reasons: list[str] = []
        if adjudication.outcome is AdjudicationOutcome.NEEDS_FOLLOW_UP:
            reasons.append("automatic_exception")
        if adjudication.proposed_status is DictionaryStatus.CONFLICT:
            reasons.append("automatic_conflict")
        if homograph.homograph_id in qa_ids:
            reasons.append("qa_sample")
        if not reasons:
            continue
        decision = decisions_by_id.get(homograph.homograph_id)
        state = (
            ExceptionReviewState.PENDING
            if decision is None
            else ExceptionReviewState(decision.review_status.value)
        )
        queue.append(
            ExceptionQueueItem(
                dictionary_version=homograph.dictionary_version,
                homograph_id=homograph.homograph_id,
                official_surface=homograph.official_surface,
                reasons=tuple(reasons),
                review_state=state,
                adjudication=adjudication,
                human_decision=decision,
            )
        )
    return tuple(sorted(queue, key=lambda item: (item.official_surface, item.homograph_id)))


def next_exception_batch(
    queue: Sequence[ExceptionQueueItem],
    *,
    limit: int,
) -> tuple[ExceptionQueueItem, ...]:
    """Return the next bounded batch that is not human-approved."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    return tuple(
        item for item in queue if item.review_state is not ExceptionReviewState.HUMAN_APPROVED
    )[:limit]


def write_review_outputs(
    output_dir: Path,
    adjudications: Sequence[AutomaticAdjudication],
    queue: Sequence[ExceptionQueueItem],
) -> dict[str, str | dict[str, str]]:
    """Write byte-deterministic adjudication and exception audit files."""

    output_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "adjudications.jsonl": _json_lines(adjudications),
        "exception-queue.jsonl": _json_lines(queue),
    }
    for name, payload in payloads.items():
        _atomic_write(output_dir / name, payload)
    file_hashes = {
        name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())
    }
    manifest: dict[str, str | dict[str, str]] = {
        "schema_version": REVIEW_OUTPUT_SCHEMA_VERSION,
        "logical_hash": hashlib.sha256(
            b"".join(payloads[name] for name in sorted(payloads))
        ).hexdigest(),
        "files": file_hashes,
    }
    _atomic_write(output_dir / "manifest.json", _json_bytes(manifest))
    return manifest


def _adjudicate_homograph(homograph: DictionaryHomograph) -> AutomaticAdjudication:
    candidates = homograph.candidates
    evidence = tuple(_candidate_evidence(candidate) for candidate in candidates)
    status, outcome, confidence, rule_code = _classify(evidence)
    evidence_hash = _evidence_hash(evidence, rule_code)
    return AutomaticAdjudication(
        dictionary_version=homograph.dictionary_version,
        homograph_id=homograph.homograph_id,
        official_surface=homograph.official_surface,
        current_status=homograph.status,
        proposed_status=status,
        outcome=outcome,
        confidence=confidence,
        rule_code=rule_code,
        candidate_ids=tuple(item.variant_id for item in candidates),
        provenance_ids=tuple(
            sorted(provenance for item in evidence for provenance in item.provenance_ids)
        ),
        evidence=evidence,
        evidence_hash=evidence_hash,
        explanation=_explanation(rule_code),
        adjudication_schema_version=ADJUDICATION_SCHEMA_VERSION,
    )


def _candidate_evidence(candidate: DictionaryCandidate) -> CandidateReviewEvidence:
    analyses = candidate.analyses
    return CandidateReviewEvidence(
        variant_id=candidate.variant_id,
        official_stressed=candidate.official_stressed,
        lifecycle_status=candidate.lifecycle_status,
        lemmas=tuple(sorted({item.lemma for item in analyses if item.lemma})),
        meanings=tuple(sorted({item.meaning for item in analyses if item.meaning})),
        parts_of_speech=tuple(sorted({item.pos for item in analyses if item.pos})),
        lexical_signatures=tuple(
            sorted(
                {
                    (item.lemma, item.pos, item.meaning)
                    for item in analyses
                    if item.lemma and item.pos
                },
                key=lambda item: (item[0], item[1], item[2] or ""),
            )
        ),
        incomplete_lexical_provenance_ids=tuple(
            sorted(item.provenance_id for item in analyses if not item.lemma or not item.pos)
        ),
        grammatical_analyses=tuple(
            sorted(
                {
                    (
                        item.paradigm_tag,
                        item.variant_tag,
                        item.form_tag,
                        item.morphology,
                    )
                    for item in analyses
                    if item.paradigm_tag or item.variant_tag or item.form_tag or item.morphology
                }
            )
        ),
        provenance_ids=tuple(sorted(item.provenance_id for item in analyses)),
    )


def _validate_adjudication(
    adjudication: AutomaticAdjudication,
    homograph: DictionaryHomograph,
) -> None:
    if adjudication != _adjudicate_homograph(homograph):
        raise ValueError("automatic adjudication does not match the dictionary record")


def _classify(
    evidence: tuple[CandidateReviewEvidence, ...],
) -> tuple[
    DictionaryStatus | None,
    AdjudicationOutcome,
    AdjudicationConfidence,
    str,
]:
    if any(item.lifecycle_status is DictionaryStatus.CANDIDATE_ONLY for item in evidence):
        return (
            None,
            AdjudicationOutcome.NEEDS_FOLLOW_UP,
            AdjudicationConfidence.LOW,
            "candidate_only_evidence",
        )
    if any(item.incomplete_lexical_provenance_ids for item in evidence):
        return (
            None,
            AdjudicationOutcome.NEEDS_FOLLOW_UP,
            AdjudicationConfidence.LOW,
            "incomplete_lexical_evidence",
        )
    if _has_asymmetric_missing_meaning(evidence):
        return (
            None,
            AdjudicationOutcome.NEEDS_FOLLOW_UP,
            AdjudicationConfidence.LOW,
            "asymmetric_missing_meaning",
        )

    lexical_signatures = tuple(tuple(item.lexical_signatures) for item in evidence)
    distinct_signatures = {
        signature
        for candidate_signatures in lexical_signatures
        for signature in candidate_signatures
    }
    if len(distinct_signatures) == 1:
        return (
            DictionaryStatus.FREE_VARIANT,
            AdjudicationOutcome.AUTO_APPROVED,
            AdjudicationConfidence.HIGH,
            "single_shared_lexical_signature",
        )
    relation = _relation(lexical_signatures)
    if relation == "disjoint":
        return (
            DictionaryStatus.CONTEXTUAL,
            AdjudicationOutcome.AUTO_APPROVED,
            AdjudicationConfidence.HIGH,
            "disjoint_lexical_evidence",
        )
    if relation == "partial":
        return (
            DictionaryStatus.CONFLICT,
            AdjudicationOutcome.AUTO_APPROVED,
            AdjudicationConfidence.HIGH,
            "partial_lexical_overlap",
        )
    return (
        None,
        AdjudicationOutcome.NEEDS_FOLLOW_UP,
        AdjudicationConfidence.LOW,
        "ambiguous_shared_lexical_evidence",
    )


def _relation(values: tuple[tuple[object, ...], ...]) -> str:
    sets = tuple(set(item) for item in values)
    if all(item == sets[0] for item in sets[1:]):
        return "equal"
    if all(
        first.isdisjoint(second) for index, first in enumerate(sets) for second in sets[index + 1 :]
    ):
        return "disjoint"
    return "partial"


def _has_asymmetric_missing_meaning(
    evidence: tuple[CandidateReviewEvidence, ...],
) -> bool:
    missing_by_base: set[tuple[str, str]] = set()
    present_by_base: set[tuple[str, str]] = set()
    for item in evidence:
        for lemma, pos, meaning in item.lexical_signatures:
            target = missing_by_base if meaning is None else present_by_base
            target.add((lemma, pos))
    return bool(missing_by_base & present_by_base)


def _evidence_hash(
    evidence: tuple[CandidateReviewEvidence, ...],
    rule_code: str,
) -> str:
    payload = json.dumps(
        {
            "adjudication_schema_version": ADJUDICATION_SCHEMA_VERSION,
            "evidence": [asdict(item) for item in evidence],
            "rule_code": rule_code,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _explanation(rule_code: str) -> str:
    return {
        "candidate_only_evidence": "At least one candidate lacks source-dictionary support.",
        "single_shared_lexical_signature": "All candidates share one lexical signature.",
        "incomplete_lexical_evidence": "At least one linked analysis lacks lemma or POS.",
        "asymmetric_missing_meaning": "Missing meaning cannot distinguish candidate evidence.",
        "ambiguous_shared_lexical_evidence": "Candidates share multiple lexical signatures.",
    }.get(rule_code, f"GrammarDB evidence satisfied rule {rule_code}.")


def _frequency_band(frequency: int) -> str:
    if frequency >= 1000:
        return "high"
    if frequency >= 100:
        return "medium"
    return "low"


def _sample_score(seed: str, homograph_id: str) -> str:
    return hashlib.sha256(f"{seed}\0{homograph_id}".encode()).hexdigest()


def _json_lines(
    items: Sequence[AutomaticAdjudication] | Sequence[ExceptionQueueItem],
) -> bytes:
    return b"".join(_json_bytes(asdict(item), newline=True) for item in items)


def _json_bytes(value: object, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (
        json.dumps(
            value,
            default=_json_default,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + suffix
    ).encode()


def _json_default(value: object) -> str:
    assert isinstance(value, date)
    return value.isoformat()


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _parse_decision(value: str, row_number: int) -> DictionaryStatus:
    try:
        decision = DictionaryStatus(value)
    except ValueError as error:
        raise ValueError(f"row {row_number}: unknown decision") from error
    if decision not in {
        DictionaryStatus.CONTEXTUAL,
        DictionaryStatus.FREE_VARIANT,
        DictionaryStatus.CONFLICT,
    }:
        raise ValueError(f"row {row_number}: unknown decision")
    return decision


def _parse_review_status(value: str, row_number: int) -> HumanReviewStatus:
    try:
        return HumanReviewStatus(value)
    except ValueError as error:
        raise ValueError(f"row {row_number}: unknown review status") from error
