from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import homograph_bel.dictionary.review as review_module
from homograph_bel.dictionary import build_dictionary_v2
from homograph_bel.dictionary.review import (
    REVIEW_DECISION_HEADERS,
    AdjudicationConfidence,
    AdjudicationOutcome,
    ExceptionReviewState,
    HumanReviewDecision,
    HumanReviewStatus,
    adjudicate_dictionary,
    build_exception_queue,
    load_human_review_decisions,
    next_exception_batch,
    select_adjudication_qa_sample,
    select_status_overrides,
    write_review_outputs,
)
from homograph_bel.dictionary.v2 import DictionaryStatus, DictionaryV2


def _paradigm(
    paradigm_id: str,
    stressed: str,
    *,
    meaning: str | None = None,
    source: str | None = "tsbm1984",
    tag: str = "NCM",
) -> str:
    attributes = [f'pdgId="{paradigm_id}"', f'lemma="{stressed}"', f'tag="{tag}"']
    if meaning is not None:
        attributes.append(f'meaning="{meaning}"')
    source_attribute = f' slouniki="{source}"' if source is not None else ""
    return (
        f"<Paradigm {' '.join(attributes)}>"
        f'<Variant id="a" lemma="{stressed}" pravapis="A2008"{source_attribute}>'
        f'<Form tag="NS"{source_attribute}>{stressed}</Form>'
        "</Variant></Paradigm>"
    )


def _build(*paradigms: str) -> DictionaryV2:
    return build_dictionary_v2(
        "<Wordlist>" + "".join(paradigms) + "</Wordlist>",
        release="RELEASE-202601",
    )


def test_equal_comparable_evidence_is_auto_approved_free_variant() -> None:
    dictionary = _build(
        _paradigm("1", "ва+да"),
        _paradigm("2", "вада+"),
    )

    result = adjudicate_dictionary(dictionary)[0]

    assert result.current_status is dictionary.homographs[0].status
    assert result.proposed_status is DictionaryStatus.FREE_VARIANT
    assert result.outcome is AdjudicationOutcome.AUTO_APPROVED
    assert result.confidence is AdjudicationConfidence.HIGH
    assert result.rule_code == "single_shared_lexical_signature"
    assert result.evidence_hash
    assert result.provenance_ids == (
        "RELEASE-202601:1:a:0",
        "RELEASE-202601:2:a:0",
    )


def test_disjoint_meanings_are_auto_approved_contextual() -> None:
    dictionary = _build(
        _paradigm("1", "за+мак", meaning="lock"),
        _paradigm("2", "зама+к", meaning="castle"),
    )

    result = adjudicate_dictionary(dictionary)[0]

    assert result.proposed_status is DictionaryStatus.CONTEXTUAL
    assert result.outcome is AdjudicationOutcome.AUTO_APPROVED
    assert result.confidence is AdjudicationConfidence.HIGH
    assert result.rule_code == "disjoint_lexical_evidence"


def test_partial_meaning_overlap_is_an_explicit_conflict() -> None:
    dictionary = _build(
        _paradigm("1", "ва+да", meaning="shared"),
        _paradigm("2", "ва+да", meaning="first"),
        _paradigm("3", "вада+", meaning="shared"),
        _paradigm("4", "вада+", meaning="second"),
    )

    result = adjudicate_dictionary(dictionary)[0]

    assert result.proposed_status is DictionaryStatus.CONFLICT
    assert result.outcome is AdjudicationOutcome.AUTO_APPROVED
    assert result.confidence is AdjudicationConfidence.HIGH
    assert result.rule_code == "partial_lexical_overlap"


def test_grammatical_tag_separation_alone_remains_a_free_variant() -> None:
    dictionary = _build(
        _paradigm("1", "ва+да", tag="NCM"),
        _paradigm("2", "вада+", tag="NCF"),
    )

    result = adjudicate_dictionary(dictionary)[0]

    assert result.proposed_status is DictionaryStatus.FREE_VARIANT
    assert result.rule_code == "single_shared_lexical_signature"


def test_equal_multiple_lexical_signatures_require_follow_up() -> None:
    dictionary = _build(
        _paradigm("1", "ва+да", meaning="first"),
        _paradigm("2", "ва+да", meaning="second"),
        _paradigm("3", "вада+", meaning="first"),
        _paradigm("4", "вада+", meaning="second"),
    )

    result = adjudicate_dictionary(dictionary)[0]

    assert result.proposed_status is None
    assert result.outcome is AdjudicationOutcome.NEEDS_FOLLOW_UP
    assert result.rule_code == "ambiguous_shared_lexical_evidence"


def test_missing_meaning_is_neutral_and_cannot_prove_contextual_status() -> None:
    dictionary = _build(
        _paradigm("1", "ва+да"),
        _paradigm("2", "вада+", meaning="sense"),
    )

    result = adjudicate_dictionary(dictionary)[0]

    assert result.proposed_status is None
    assert result.outcome is AdjudicationOutcome.NEEDS_FOLLOW_UP
    assert result.rule_code == "asymmetric_missing_meaning"


def test_candidate_only_evidence_requires_follow_up() -> None:
    dictionary = _build(
        _paradigm("1", "ва+да", source=None),
        _paradigm("2", "вада+", source=None),
    )

    result = adjudicate_dictionary(dictionary)[0]

    assert result.proposed_status is None
    assert result.outcome is AdjudicationOutcome.NEEDS_FOLLOW_UP
    assert result.confidence is AdjudicationConfidence.LOW
    assert result.rule_code == "candidate_only_evidence"


def test_incomplete_comparable_evidence_requires_follow_up() -> None:
    dictionary = _build(
        _paradigm("1", "ва+да", tag=""),
        _paradigm("2", "вада+", tag=""),
    )

    result = adjudicate_dictionary(dictionary)[0]

    assert result.proposed_status is None
    assert result.rule_code == "incomplete_lexical_evidence"


def test_one_incomplete_analysis_blocks_complete_sibling_evidence() -> None:
    dictionary = _build(
        _paradigm("1", "ва+да"),
        _paradigm("2", "ва+да", tag=""),
        _paradigm("3", "вада+"),
    )

    result = adjudicate_dictionary(dictionary)[0]

    assert result.proposed_status is None
    assert result.rule_code == "incomplete_lexical_evidence"


def _write_decisions(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(REVIEW_DECISION_HEADERS)
        writer.writerows([row[header] for header in REVIEW_DECISION_HEADERS] for row in rows)


def _valid_decision(dictionary: DictionaryV2) -> dict[str, str]:
    homograph = dictionary.homographs[0]
    return {
        "dictionary_version": dictionary.release,
        "homograph_id": homograph.homograph_id,
        "official_surface": homograph.official_surface,
        "decision": "contextual",
        "review_status": "human_approved",
        "reviewer": "reviewer@example.test",
        "reviewed_at": "2026-07-17",
        "evidence": "GrammarDB meanings distinguish the candidates.",
        "reviewer_note": "Checked both analyses.",
        "review_schema_version": "dictionary-human-review-v1",
    }


def test_human_decision_csv_is_strict_and_cross_checked(tmp_path: Path) -> None:
    dictionary = _build(
        _paradigm("1", "за+мак", meaning="lock"),
        _paradigm("2", "зама+к", meaning="castle"),
    )
    path = tmp_path / "decisions.csv"
    row = _valid_decision(dictionary)
    _write_decisions(path, [row])

    decisions = load_human_review_decisions(path, dictionary)

    assert len(decisions) == 1
    assert decisions[0].decision is DictionaryStatus.CONTEXTUAL
    assert decisions[0].review_status is HumanReviewStatus.HUMAN_APPROVED
    assert decisions[0].reviewed_at.isoformat() == "2026-07-17"

    _write_decisions(path, [])
    assert load_human_review_decisions(path, dictionary) == ()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("dictionary_version", "other", "unknown dictionary release"),
        ("homograph_id", "unknown", "unknown homograph ID"),
        ("official_surface", "wrong", "surface does not match"),
        ("decision", "unknown", "unknown decision"),
        ("decision", "candidate_only", "unknown decision"),
        ("review_status", "unknown", "unknown review status"),
        ("reviewed_at", "17-07-2026", "invalid reviewed_at"),
        ("evidence", "", "blank required field"),
        ("review_schema_version", "other", "unknown review schema"),
    ],
)
def test_human_decision_csv_rejects_invalid_rows(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    dictionary = _build(_paradigm("1", "ва+да"), _paradigm("2", "вада+"))
    row = _valid_decision(dictionary)
    row[field] = value
    path = tmp_path / "decisions.csv"
    _write_decisions(path, [row])

    with pytest.raises(ValueError, match=message):
        load_human_review_decisions(path, dictionary)


def test_human_decision_csv_rejects_headers_and_duplicate_keys(tmp_path: Path) -> None:
    dictionary = _build(_paradigm("1", "ва+да"), _paradigm("2", "вада+"))
    path = tmp_path / "decisions.csv"
    path.write_text("wrong,headers\n", encoding="utf-8")
    with pytest.raises(ValueError, match="headers"):
        load_human_review_decisions(path, dictionary)

    row = _valid_decision(dictionary)
    _write_decisions(path, [row, row])
    with pytest.raises(ValueError, match="duplicate decision"):
        load_human_review_decisions(path, dictionary)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(REVIEW_DECISION_HEADERS)
        writer.writerow([row[header] for header in REVIEW_DECISION_HEADERS] + ["extra"])
    with pytest.raises(ValueError, match="unexpected columns"):
        load_human_review_decisions(path, dictionary)


def _human_decision(
    dictionary: DictionaryV2,
    *,
    homograph_index: int = 0,
    decision: DictionaryStatus = DictionaryStatus.CONTEXTUAL,
    review_status: HumanReviewStatus = HumanReviewStatus.HUMAN_APPROVED,
) -> HumanReviewDecision:
    homograph = dictionary.homographs[homograph_index]
    return HumanReviewDecision(
        dictionary_version=dictionary.release,
        homograph_id=homograph.homograph_id,
        official_surface=homograph.official_surface,
        decision=decision,
        review_status=review_status,
        reviewer="reviewer@example.test",
        reviewed_at=date(2026, 7, 17),
        evidence="Reviewed GrammarDB evidence.",
        reviewer_note="Explicit review decision.",
    )


def test_high_confidence_automatic_and_human_approved_status_precedence() -> None:
    dictionary = _build(_paradigm("1", "ва+да"), _paradigm("2", "вада+"))
    automatic = adjudicate_dictionary(dictionary)

    assert select_status_overrides(dictionary, automatic) == {"вада": DictionaryStatus.FREE_VARIANT}
    assert select_status_overrides(
        dictionary,
        automatic,
        (_human_decision(dictionary),),
    ) == {"вада": DictionaryStatus.CONTEXTUAL}
    assert (
        select_status_overrides(
            dictionary,
            automatic,
            (
                _human_decision(
                    dictionary,
                    review_status=HumanReviewStatus.NEEDS_FOLLOW_UP,
                ),
            ),
        )
        == {}
    )


def test_status_overrides_reject_inconsistent_automatic_results() -> None:
    dictionary = _build(_paradigm("1", "ва+да"), _paradigm("2", "вада+"))
    automatic = adjudicate_dictionary(dictionary)[0]

    with pytest.raises(ValueError, match="does not match"):
        select_status_overrides(
            dictionary,
            (replace(automatic, confidence=AdjudicationConfidence.LOW),),
        )

    with pytest.raises(ValueError, match="cover every homograph"):
        select_status_overrides(dictionary, ())
    with pytest.raises(ValueError, match="does not match"):
        select_status_overrides(
            dictionary,
            (replace(automatic, rule_code="tampered"),),
        )


def test_rule_schema_version_changes_the_adjudication_evidence_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dictionary = _build(_paradigm("1", "ва+да"), _paradigm("2", "вада+"))
    first = adjudicate_dictionary(dictionary)[0]
    monkeypatch.setattr(review_module, "ADJUDICATION_SCHEMA_VERSION", "dictionary-adjudication-v2")

    second = adjudicate_dictionary(dictionary)[0]

    assert second.adjudication_schema_version == "dictionary-adjudication-v2"
    assert second.evidence_hash != first.evidence_hash


def test_status_overrides_reject_mismatched_and_duplicate_review_records() -> None:
    dictionary = _build(_paradigm("1", "ва+да"), _paradigm("2", "вада+"))
    automatic = adjudicate_dictionary(dictionary)
    decision = _human_decision(dictionary)

    with pytest.raises(ValueError, match="unique homograph IDs"):
        select_status_overrides(dictionary, automatic, (decision, decision))
    with pytest.raises(ValueError, match="unknown homograph ID"):
        select_status_overrides(
            dictionary,
            automatic,
            (replace(decision, homograph_id="unknown"),),
        )
    with pytest.raises(ValueError, match="does not match"):
        select_status_overrides(
            dictionary,
            automatic,
            (replace(decision, official_surface="wrong"),),
        )
    with pytest.raises(ValueError, match="linguistic status"):
        select_status_overrides(
            dictionary,
            automatic,
            (replace(decision, decision=DictionaryStatus.CANDIDATE_ONLY),),
        )
    with pytest.raises(ValueError, match="review schema"):
        select_status_overrides(
            dictionary,
            automatic,
            (replace(decision, review_schema_version="other"),),
        )
    with pytest.raises(ValueError, match="does not match"):
        select_status_overrides(
            dictionary,
            (replace(automatic[0], official_surface="wrong"),),
        )


def _review_dictionary() -> DictionaryV2:
    return _build(
        _paradigm("1", "ва+да"),
        _paradigm("2", "вада+"),
        _paradigm("3", "за+мак", meaning="lock"),
        _paradigm("4", "зама+к", meaning="castle"),
        _paradigm("5", "на+га", meaning="shared"),
        _paradigm("6", "на+га", meaning="first"),
        _paradigm("7", "нага+", meaning="shared"),
        _paradigm("8", "нага+", meaning="second"),
        _paradigm("9", "ру+ка", source=None),
        _paradigm("10", "рука+", source=None),
    )


def test_qa_sample_is_deterministic_across_status_and_frequency_bands() -> None:
    dictionary = _review_dictionary()
    adjudications = adjudicate_dictionary(dictionary)
    frequencies = {"вада": 2000, "замак": 200, "нага": 2, "рука": 2}

    sample = select_adjudication_qa_sample(
        adjudications,
        frequencies=frequencies,
        sample_size=3,
        seed="review-v1",
    )

    assert len(sample) == 3
    assert set(sample) == {
        item.homograph_id
        for item in adjudications
        if item.outcome is AdjudicationOutcome.AUTO_APPROVED
    }
    assert sample == select_adjudication_qa_sample(
        tuple(reversed(adjudications)),
        frequencies=frequencies,
        sample_size=3,
        seed="review-v1",
    )
    with pytest.raises(ValueError, match="sample_size"):
        select_adjudication_qa_sample(
            adjudications,
            frequencies=frequencies,
            sample_size=-1,
            seed="review-v1",
        )


def test_exception_queue_is_ordered_auditable_and_resumable() -> None:
    dictionary = _review_dictionary()
    adjudications = adjudicate_dictionary(dictionary)
    sample = select_adjudication_qa_sample(
        adjudications,
        frequencies={"вада": 2000, "замак": 200, "нага": 2, "рука": 2},
        sample_size=3,
        seed="review-v1",
    )
    decisions = (
        _human_decision(dictionary, homograph_index=0),
        _human_decision(
            dictionary,
            homograph_index=3,
            review_status=HumanReviewStatus.NEEDS_FOLLOW_UP,
        ),
    )

    queue = build_exception_queue(
        dictionary,
        adjudications,
        human_decisions=decisions,
        qa_homograph_ids=sample,
    )

    assert [item.official_surface for item in queue] == ["вада", "замак", "нага", "рука"]
    assert queue[0].review_state is ExceptionReviewState.HUMAN_APPROVED
    assert queue[0].reasons == ("qa_sample",)
    assert queue[1].review_state is ExceptionReviewState.PENDING
    assert queue[2].review_state is ExceptionReviewState.PENDING
    assert queue[2].reasons == ("automatic_conflict", "qa_sample")
    assert queue[3].review_state is ExceptionReviewState.NEEDS_FOLLOW_UP
    assert queue[3].reasons == ("automatic_exception",)
    assert queue[3].adjudication.evidence[0].provenance_ids
    assert next_exception_batch(queue, limit=1) == (queue[1],)
    assert next_exception_batch(queue, limit=5) == (queue[1], queue[2], queue[3])
    with pytest.raises(ValueError, match="limit"):
        next_exception_batch(queue, limit=0)
    with pytest.raises(ValueError, match="unknown homograph IDs"):
        build_exception_queue(
            dictionary,
            adjudications,
            qa_homograph_ids=("unknown",),
        )


def test_review_outputs_are_atomic_and_byte_deterministic(tmp_path: Path) -> None:
    dictionary = _review_dictionary()
    adjudications = adjudicate_dictionary(dictionary)
    queue = build_exception_queue(
        dictionary,
        adjudications,
        human_decisions=(
            _human_decision(
                dictionary,
                homograph_index=3,
                review_status=HumanReviewStatus.NEEDS_FOLLOW_UP,
            ),
        ),
    )

    manifest = write_review_outputs(tmp_path, adjudications, queue)
    first = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    repeated = write_review_outputs(tmp_path, adjudications, queue)

    assert manifest == repeated
    assert first == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert set(manifest["files"]) == {"adjudications.jsonl", "exception-queue.jsonl"}
    assert not list(tmp_path.glob("*.tmp"))
    first_adjudication = json.loads(
        (tmp_path / "adjudications.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert first_adjudication["evidence"]
    assert first_adjudication["evidence_hash"]
    exceptions = [
        json.loads(line)
        for line in (tmp_path / "exception-queue.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    exception = next(item for item in exceptions if item["human_decision"] is not None)
    assert exception["human_decision"]["reviewed_at"] == "2026-07-17"
