from __future__ import annotations

import unicodedata
from collections.abc import Iterator

import pytest

from homograph_bel.dictionary.index import DictionaryIndex
from homograph_bel.dictionary.v2 import (
    DictionaryCandidate,
    DictionaryHomograph,
    DictionaryStatus,
    GrammarDBAnalysis,
)
from homograph_bel.inference import LeanAdjudicationPrompt, LeanAdjudicationResult
from homograph_bel.inference.dictionary import (
    LEAN_PROMPT_VERSION,
    LEAN_SYSTEM_PROMPT,
    PROMPT_VERSION,
    HomographOccurrence,
    HomographScanner,
    LeanResponseStatus,
    PromptContractError,
    build_adjudication_prompt,
    build_lean_adjudication_prompt,
    parse_lean_adjudication_response,
)


def _analysis(
    *, variant_id: str, lemma: str, pos: str, meaning: str, morphology: tuple[str, ...]
) -> GrammarDBAnalysis:
    return GrammarDBAnalysis(
        release="test-release",
        source_paradigm_id=f"p-{variant_id}",
        source_variant_id="a",
        source_form_id="1",
        lemma=lemma,
        stressed_lemma=lemma,
        pos=pos,
        paradigm_tag=pos,
        variant_tag="",
        form_tag="FORM",
        meaning=meaning,
        theme=None,
        regulation=None,
        variant_type=None,
        form_type=None,
        form_options=None,
        source_dictionaries=("grammadb",),
        orthographies=("A2008",),
        morphology=morphology,
        phonetic_forms=(),
        notes=(),
    )


def _homograph(
    homograph_id: str,
    surface: str,
    stressed: tuple[str, str],
    status: DictionaryStatus = DictionaryStatus.CONTEXTUAL,
) -> DictionaryHomograph:
    candidates = tuple(
        DictionaryCandidate(
            homograph_id=homograph_id,
            variant_id=f"{homograph_id}-v{number}",
            official_surface=surface,
            official_stressed=spelling,
            stress_position=number - 1,
            status=status,
            lifecycle_status=DictionaryStatus.PRODUCTION_SUPPORTED,
            analyses=(
                _analysis(
                    variant_id=f"v{number}",
                    lemma=f"lemma-{number}",
                    pos="N" if number == 1 else "V",
                    meaning=f"meaning-{number}",
                    morphology=(f"Form={number}",),
                ),
            ),
            provenance=(f"test-release:p-v{number}:a:1",),
        )
        for number, spelling in enumerate(stressed, start=1)
    )
    return DictionaryHomograph(homograph_id, surface, "test-release", status, candidates)


def _index() -> DictionaryIndex:
    return DictionaryIndex(
        "test-release",
        (
            _homograph("h-abjava", "аб'ява", ("аб'я́ва", "аб'ява́")),
            _homograph(
                "h-vada",
                "вада",
                ("ва́да", "вада́"),
                DictionaryStatus.FREE_VARIANT,
            ),
            _homograph("h-syoly", "сёлы", ("сё́лы", "сёлы́")),
            _homograph("h-moi", "мой", ("мо́й", "мой́")),
            _homograph("h-vouk", "воўк", ("во́ўк", "воўќ")),
        ),
    )


def _plachu_index() -> DictionaryIndex:
    def analysis(
        paradigm_id: str,
        lemma: str,
        pos: str,
        paradigm_tag: str,
        form_tag: str,
        meaning: str | None = None,
    ) -> GrammarDBAnalysis:
        return GrammarDBAnalysis(
            release="RELEASE-202601",
            source_paradigm_id=paradigm_id,
            source_variant_id="a",
            source_form_id="1",
            lemma=lemma,
            stressed_lemma=lemma,
            pos=pos,
            paradigm_tag=paradigm_tag,
            variant_tag="",
            form_tag=form_tag,
            meaning=meaning,
            theme=None,
            regulation=None,
            variant_type=None,
            form_type=None,
            form_options=None,
            source_dictionaries=("sbm2012",),
            orthographies=("A2008",),
            morphology=(),
            phonetic_forms=(),
            notes=(),
        )

    candidates = (
        DictionaryCandidate(
            "h-plachu",
            "v-pay",
            "плачу",
            "плачу́",
            1,
            DictionaryStatus.CONTEXTUAL,
            DictionaryStatus.PRODUCTION_SUPPORTED,
            (
                analysis("pay", "плаціць", "V", "VDMN2", "R1S", "аддаваць грошы"),
                analysis("pay", "плаціць", "V", "VDMN2", "R1S", "аддаваць грошы"),
            ),
            ("RELEASE-202601:pay:a:1", "RELEASE-202601:pay:a:1"),
        ),
        DictionaryCandidate(
            "h-plachu",
            "v-cry",
            "плачу",
            "пла́чу",
            0,
            DictionaryStatus.CONTEXTUAL,
            DictionaryStatus.PRODUCTION_SUPPORTED,
            (
                analysis("noun", "плач", "N", "NCIINM1", "GS"),
                analysis("noun-subst", "плач", "N", "NCIINS5", "MGS"),
                analysis("noun", "плач", "N", "NCIINM1", "DS"),
                analysis("cry", "плакаць", "V", "VIMN1", "R1S"),
            ),
            (
                "RELEASE-202601:noun:a:1",
                "RELEASE-202601:noun-subst:a:1",
                "RELEASE-202601:noun:a:1",
                "RELEASE-202601:cry:a:1",
            ),
        ),
    )
    return DictionaryIndex(
        "RELEASE-202601",
        (
            DictionaryHomograph(
                "h-plachu", "плачу", "RELEASE-202601", DictionaryStatus.CONTEXTUAL, candidates
            ),
        ),
    )


def test_scans_unicode_words_and_preserves_exact_offsets() -> None:
    text = "Абʼява, аб'яваць і АБ’ЯВА; вадавада, Вада."

    occurrences = HomographScanner(_index()).scan(text)

    assert [item.target_surface for item in occurrences] == ["Абʼява", "АБ’ЯВА", "Вада"]
    assert [text[item.target_start : item.target_end] for item in occurrences] == [
        "Абʼява",
        "АБ’ЯВА",
        "Вада",
    ]
    assert [item.target_normalized for item in occurrences] == ["аб'ява", "аб'ява", "вада"]
    assert occurrences[0].homograph_id == "h-abjava"
    assert occurrences[0].candidate_ids == ("h-abjava-v1", "h-abjava-v2")
    assert occurrences[0].dictionary_version == "test-release"
    assert occurrences[0].status is DictionaryStatus.CONTEXTUAL


def test_scans_decomposed_stress_and_repeated_occurrences_in_order() -> None:
    text = "ВА\N{COMBINING ACUTE ACCENT}ДА і вада-вада: вада"

    occurrences = HomographScanner(_index()).scan(text)

    assert [item.target_surface for item in occurrences] == [
        "ВА\N{COMBINING ACUTE ACCENT}ДА",
        "вада",
    ]
    assert [item.target_start for item in occurrences] == sorted(
        item.target_start for item in occurrences
    )
    assert all(
        text[item.target_start : item.target_end] == item.target_surface for item in occurrences
    )


def test_scans_nfd_belarusian_letters_and_all_supported_stress_markers() -> None:
    decomposed = unicodedata.normalize("NFD", "сёлы мой воўк")

    occurrences = HomographScanner(_index()).scan(decomposed)

    assert [item.target_normalized for item in occurrences] == ["сёлы", "мой", "воўк"]
    assert all(
        decomposed[item.target_start : item.target_end] == item.target_surface
        for item in occurrences
    )

    stressed = "ва+да ва\N{ACUTE ACCENT}да"
    stressed_occurrences = HomographScanner(_index()).scan(stressed)
    assert [item.target_surface for item in stressed_occurrences] == [
        "ва+да",
        "ва\N{ACUTE ACCENT}да",
    ]

    leading = "+вада \N{ACUTE ACCENT}вада"
    leading_occurrences = HomographScanner(_index()).scan(leading)
    assert [item.target_surface for item in leading_occurrences] == ["вада", "вада"]
    assert HomographScanner(_index()).scan("ва++++да вад+а") == ()


def test_scan_many_is_lazy_and_handles_empty_or_unmatched_text() -> None:
    consumed: list[str] = []

    def texts() -> Iterator[str]:
        for text in ("вада", "нічога", ""):
            consumed.append(text)
            yield text

    batches = HomographScanner(_index()).scan_many(texts())
    assert consumed == []
    assert [item.target_surface for item in next(batches)] == ["вада"]
    assert consumed == ["вада"]
    assert next(batches) == ()
    assert next(batches) == ()
    with pytest.raises(StopIteration):
        next(batches)


def test_builds_a_deterministic_closed_candidate_prompt() -> None:
    occurrence = HomographScanner(_index()).scan("Гэта аб'ява для ўсіх.")[0]

    result = build_adjudication_prompt(
        occurrence,
        observed_morphology={"Case": "Nom", "Number": "Sing"},
        examples=("Падобны правераны прыклад.",),
    )
    repeated = build_adjudication_prompt(
        occurrence,
        observed_morphology={"Case": "Nom", "Number": "Sing"},
        examples=("Падобны правераны прыклад.",),
    )

    assert result == repeated
    assert result.version == PROMPT_VERSION
    assert len(result.prompt_hash) == 64
    assert "Гэта аб'ява для ўсіх." in result.prompt
    assert "Гэта <target>аб'ява</target> для ўсіх." in result.prompt
    assert f"characters {occurrence.target_start}:{occurrence.target_end}" in result.prompt
    for candidate in occurrence.homograph.candidates:
        assert candidate.variant_id in result.prompt
        assert candidate.official_stressed in result.prompt
        assert candidate.analyses[0].lemma in result.prompt
        assert candidate.analyses[0].pos in result.prompt
        assert candidate.analyses[0].morphology[0] in result.prompt
        assert candidate.analyses[0].meaning is not None
        assert candidate.analyses[0].meaning in result.prompt
        assert candidate.provenance[0] in result.prompt
    assert '"Case":"Nom"' in result.prompt
    assert "Падобны правераны прыклад." in result.prompt
    assert '"selected_candidate_id"' in result.prompt
    assert '"ambiguous_or_insufficient"' in result.prompt


def test_prompt_omits_optional_evidence_and_rejects_invalid_input() -> None:
    occurrence = HomographScanner(_index()).scan("вада")[0]

    result = build_adjudication_prompt(occurrence)
    assert "Observed morphology" not in result.prompt
    assert "Examples" not in result.prompt

    with pytest.raises(PromptContractError, match="examples"):
        build_adjudication_prompt(occurrence, examples=("",))
    with pytest.raises(PromptContractError, match="morphology"):
        build_adjudication_prompt(occurrence, observed_morphology={"Case": ""})


def test_builds_lean_prompt_with_decoded_candidate_evidence() -> None:
    occurrence = HomographScanner(_plachu_index()).scan("Я плачу за квіткі.")[0]

    result = build_lean_adjudication_prompt(occurrence)
    repeated = build_lean_adjudication_prompt(occurrence)

    assert result == repeated
    assert isinstance(result, LeanAdjudicationPrompt)
    assert result.version == LEAN_PROMPT_VERSION
    assert result.system_prompt == LEAN_SYSTEM_PROMPT
    assert result.candidate_ids == ("v-pay", "v-cry")
    assert len(result.prompt_hash) == 64
    assert result.user_prompt.splitlines()[0] == "Я <t>плачу</t> за квіткі."
    assert (
        "1 плачу́ | плаціць; VERB; Number=Sing; Person=1; Tense=Present; "
        "Aspect=Imperfective; Meaning=аддаваць грошы"
    ) in result.user_prompt
    assert (
        "плач; NOUN; Forms=Case=Gen,Number=Sing,Gender=Masc,Animacy=Inan | "
        "Case=Dat,Number=Sing,Gender=Masc,Animacy=Inan"
    ) in result.user_prompt
    assert "плакаць; VERB; Number=Sing; Person=1; Tense=Present" in result.user_prompt
    assert "v-pay" not in result.user_prompt
    assert "RELEASE-202601" not in result.user_prompt
    assert result.user_prompt.count("плаціць; VERB") == 1
    assert result.user_prompt.count("плач; NOUN; Forms=Case=Gen") == 1
    assert result.user_prompt.count("плач; NOUN") == 1


def test_parses_lean_choice_and_returns_possible_analyses() -> None:
    occurrence = HomographScanner(_plachu_index()).scan("Я плачу за квіткі.")[0]
    prompt = build_lean_adjudication_prompt(occurrence)

    result = parse_lean_adjudication_response(prompt, " 2\n")

    assert isinstance(result, LeanAdjudicationResult)
    assert result.status is LeanResponseStatus.SELECTED
    assert result.selected_candidate_id == "v-cry"
    assert {analysis.pos for analysis in result.possible_analyses} == {"NOUN", "VERB"}
    assert result.raw_response == " 2\n"


@pytest.mark.parametrize("response", ("", "0", "3", "1 because", "{}"))
def test_rejects_malformed_lean_choices(response: str) -> None:
    occurrence = HomographScanner(_plachu_index()).scan("Я плачу.")[0]
    prompt = build_lean_adjudication_prompt(occurrence)

    result = parse_lean_adjudication_response(prompt, response)

    assert result.status is LeanResponseStatus.INVALID
    assert result.selected_candidate_id is None
    assert result.possible_analyses == ()


def test_accepts_explicit_lean_abstention() -> None:
    occurrence = HomographScanner(_plachu_index()).scan("Я плачу.")[0]
    prompt = build_lean_adjudication_prompt(occurrence)

    result = parse_lean_adjudication_response(prompt, " ? ")

    assert result.status is LeanResponseStatus.ABSTAINED
    assert result.selected_candidate_id is None
    assert result.possible_analyses == ()


def test_occurrence_rejects_inconsistent_offsets() -> None:
    occurrence = HomographScanner(_index()).scan("вада")[0]

    with pytest.raises(ValueError, match="offsets"):
        HomographOccurrence(
            text=occurrence.text,
            target_start=0,
            target_end=3,
            target_surface="вада",
            target_normalized="вада",
            homograph=occurrence.homograph,
        )


def test_occurrence_rejects_invalid_ranges_normalization_and_homograph() -> None:
    occurrence = HomographScanner(_index()).scan("вада")[0]
    with pytest.raises(ValueError, match="range"):
        HomographOccurrence("вада", -4, 4, "вада", "вада", occurrence.homograph)
    with pytest.raises(ValueError, match="normalized"):
        HomographOccurrence("вада", 0, 4, "вада", "іншае", occurrence.homograph)
    other = _index().get_homograph("аб'ява")
    assert other is not None
    with pytest.raises(ValueError, match="homograph"):
        HomographOccurrence("вада", 0, 4, "вада", "вада", other)
