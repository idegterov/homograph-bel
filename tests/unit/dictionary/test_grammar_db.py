from pathlib import Path

import pytest

from homograph_bel.datasets.contracts import Orthography
from homograph_bel.dictionary.grammar_db import (
    ClassicalMapping,
    DictionaryIndex,
    load_classical_overlay,
    normalize_unstressed,
)


def test_normalize_unstressed_removes_only_acute_and_case_folds() -> None:
    assert normalize_unstressed("ЗА́МАК") == "замак"
    assert normalize_unstressed("аб'ё́м") == "аб'ём"


def test_dictionary_keeps_only_distinct_valid_homograph_variants() -> None:
    index = DictionaryIndex.from_lines(
        [
            "за́мак\n",
            "зама́к\n",
            "за́мак\n",
            "до́м\n",
            "ма́ма́\n",
            "б́ла\n",
            "\n",
        ],
        version="test-1",
    )

    assert [(item.official_surface, item.official_stressed) for item in index.variants] == [
        ("замак", "зама́к"),
        ("замак", "за́мак"),
    ]
    assert index.report.total_lines == 7
    assert index.report.invalid_lines == 2
    assert index.report.duplicate_variants == 1
    assert index.report.homographs == 1
    assert index.report.variants == 2


def test_dictionary_ids_are_stable_across_input_order() -> None:
    first = DictionaryIndex.from_lines(["за́мак", "зама́к"], version="test")
    second = DictionaryIndex.from_lines(["зама́к", "за́мак"], version="test")

    assert [(item.homograph_id, item.variant_id) for item in first.variants] == [
        (item.homograph_id, item.variant_id) for item in second.variants
    ]
    assert first.variants[0].homograph_id.startswith("h_")
    assert first.variants[0].variant_id.startswith("v_")


def test_dictionary_detects_shortened_identifier_collisions() -> None:
    def colliding_identifier(prefix: str, _parts: tuple[str, ...]) -> str:
        return f"{prefix}_same"

    with pytest.raises(ValueError, match="identifier collision"):
        DictionaryIndex.from_lines(
            ["за́мак", "зама́к"],
            version="test",
            identifier=colliding_identifier,
        )


def test_official_and_approved_classical_variants_resolve_to_canonical_ids() -> None:
    mapping = ClassicalMapping(
        classical_surface="сьвяты",
        classical_stressed="сьвя́ты",
        official_surface="святы",
        official_stressed="свя́ты",
        evidence="team review",
        reviewer_note="paired spelling",
        status="approved",
        version="overlay-1",
    )
    index = DictionaryIndex.from_lines(
        ["свя́ты", "святы́"],
        version="test",
        classical_mappings=[mapping],
    )

    official = index.resolve("Святы", "свя́ты")
    classical = index.resolve("СЬВЯТЫ", "сьвя́ты")

    assert official.orthography is Orthography.OFFICIAL_2008
    assert classical.orthography is Orthography.CLASSICAL
    assert official.variant == classical.variant
    assert classical.mapping_version == "overlay-1"


def test_unapproved_classical_and_unknown_variants_stay_unresolved() -> None:
    pending = ClassicalMapping(
        classical_surface="сьвяты",
        classical_stressed="сьвя́ты",
        official_surface="святы",
        official_stressed="свя́ты",
        evidence="automatic suggestion",
        reviewer_note="needs review",
        status="pending",
        version="overlay-1",
    )
    index = DictionaryIndex.from_lines(
        ["свя́ты", "святы́"],
        version="test",
        classical_mappings=[pending],
    )

    unresolved = index.resolve("сьвяты", "сьвя́ты")
    forbidden = index.resolve("святы", "свя́ты́")
    unknown = index.resolve("невядома", "невядо́ма")

    assert unresolved.orthography is Orthography.MIXED_OR_UNKNOWN
    assert unresolved.reason == "classical_mapping_not_approved"
    assert forbidden.orthography is Orthography.OFFICIAL_2008
    assert forbidden.reason == "dictionary_variant_not_allowed"
    assert unknown.orthography is Orthography.MIXED_OR_UNKNOWN
    assert unknown.reason == "dictionary_target_missing"


def test_classical_overlay_rejects_unknown_official_variant() -> None:
    mapping = ClassicalMapping(
        classical_surface="сьвяты",
        classical_stressed="сьвя́ты",
        official_surface="святы",
        official_stressed="свято́е",
        evidence="team review",
        reviewer_note="bad target",
        status="approved",
        version="overlay-1",
    )

    with pytest.raises(ValueError, match="unknown official variant"):
        DictionaryIndex.from_lines(
            ["свя́ты", "святы́"],
            version="test",
            classical_mappings=[mapping],
        )


def test_load_classical_overlay_validates_headers_and_values(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.csv"
    overlay.write_text(
        "classical_surface,classical_stressed,official_surface,official_stressed,"
        "evidence,reviewer_note,status,version\n"
        "сьвяты,сьвя́ты,святы,свя́ты,team,checked,approved,v1\n",
        encoding="utf-8",
    )

    assert load_classical_overlay(overlay) == [
        ClassicalMapping(
            classical_surface="сьвяты",
            classical_stressed="сьвя́ты",
            official_surface="святы",
            official_stressed="свя́ты",
            evidence="team",
            reviewer_note="checked",
            status="approved",
            version="v1",
        )
    ]

    overlay.write_text("wrong,header\nvalue,row\n", encoding="utf-8")
    with pytest.raises(ValueError, match="classical overlay headers"):
        load_classical_overlay(overlay)
