from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

from homograph_bel.dictionary.grammar_db import (
    DictionaryStatus,
    DictionaryV1Identity,
    GrammarDBParseError,
    build_dictionary_v2,
    migrate_dictionary_v1_ids,
    select_dictionary_qa_sample,
)

XML = """
<Wordlist>
  <Paradigm pdgId="10" lemma="за́мак" tag="NCM">
    <Variant id="a" lemma="за́мак" slouniki="tsbm1984" pravapis="A2008">
      <Form tag="NS" slouniki="tsbm1984">за+мак</Form>
    </Variant>
  </Paradigm>
  <Paradigm pdgId="11" lemma="зама́к" tag="NCM" meaning="building">
    <Variant id="a" lemma="зама́к" slouniki="tsbm1984" pravapis="A2008">
      <Slounik name="nested" idx="1">entry</Slounik>
      <Morph>morphology</Morph>
      <Fan s="phonetic">phonetic</Fan>
      <Note>source note</Note>
      <Form tag="NS" slouniki="tsbm1984">зама+к</Form>
    </Variant>
  </Paradigm>
  <Paradigm pdgId="13" lemma="зама́к" tag="NCM" meaning="building variant">
    <Variant id="b" lemma="зама́к" slouniki="sbm2012" pravapis="A2008">
      <Form tag="GS" slouniki="sbm2012">зама+к</Form>
    </Variant>
  </Paradigm>
  <Paradigm pdgId="12" lemma="замо́к" tag="NCM" meaning="lock">
    <Variant id="a" lemma="замо́к" slouniki="tsbm1984" pravapis="A1957">
      <Form tag="NS" slouniki="tsbm1984">замо+к</Form>
    </Variant>
  </Paradigm>
</Wordlist>
"""


def test_xml_build_preserves_metadata_and_groups_same_stress() -> None:
    dictionary = build_dictionary_v2(XML, release="RELEASE-202601")

    assert len(dictionary.homographs) == 1
    homograph = dictionary.homographs[0]
    assert homograph.official_surface == "замак"
    assert [candidate.official_stressed for candidate in homograph.candidates] == [
        "зама́к",
        "за́мак",
    ]
    assert len(homograph.candidates[0].analyses) == 2
    analysis = homograph.candidates[0].analyses[0]
    assert analysis.paradigm_id == "11"
    assert analysis.variant_id == "a"
    assert analysis.form_tag == "NS"
    assert analysis.meaning == "building"
    assert analysis.source_dictionaries == ("nested", "tsbm1984")
    assert analysis.morphology == ("morphology",)
    assert analysis.phonetic_forms == ("phonetic",)
    assert analysis.notes == ("source note",)
    assert analysis.form_id == "0"
    assert homograph.candidates[0].status is DictionaryStatus.CONTEXTUAL
    assert homograph.candidates[0].lifecycle_status is DictionaryStatus.PRODUCTION_SUPPORTED
    assert len(dictionary.analyses) == 3
    assert dictionary.report.excluded_records == 1


def test_xml_parser_rejects_malformed_stress_and_non_xml_root() -> None:
    malformed = "<Wordlist><Paradigm pdgId='1' lemma='слова'><Variant lemma='слова' pravapis='A2008'><Form tag='NS'>слова</Form></Variant></Paradigm></Wordlist>"
    dictionary = build_dictionary_v2(malformed, release="test")
    assert dictionary.report.invalid_forms == 1
    assert dictionary.homographs == ()

    with pytest.raises(GrammarDBParseError, match="Wordlist"):
        build_dictionary_v2("<Other />", release="test")


def test_xml_build_is_deterministic_for_input_order_and_unicode_form() -> None:
    first = build_dictionary_v2(XML, release="RELEASE-202601")
    root = ET.fromstring(XML)
    root[:] = reversed(root[:])
    second_xml = ET.tostring(root, encoding="unicode")
    second = build_dictionary_v2(second_xml, release="RELEASE-202601")
    assert first.logical_hash == build_dictionary_v2(XML, release="RELEASE-202601").logical_hash
    assert first.logical_hash == second.logical_hash
    assert first.report.logical_hash == first.logical_hash


def test_migration_preserves_old_identity_and_deprecates_changed_pronunciation() -> None:
    dictionary = build_dictionary_v2(XML, release="RELEASE-202601")
    old = (
        DictionaryV1Identity(
            homograph_id="old-h",
            variant_id="old-v",
            official_surface="замак",
            official_stressed="за́мак",
        ),
        DictionaryV1Identity(
            homograph_id="old-h",
            variant_id="old-lock",
            official_surface="замак",
            official_stressed="замо́к",
        ),
    )
    migration = migrate_dictionary_v1_ids(old, dictionary)
    kept = next(item for item in migration.mappings if item.old_variant_id == "old-v")
    changed = next(item for item in migration.mappings if item.old_variant_id == "old-lock")
    assert kept.new_variant_id == dictionary.homographs[0].candidates[1].variant_id
    assert kept.status == "preserved"
    assert changed.new_variant_id is None
    assert changed.status == "deprecated"
    assert migration.logical_hash


def test_statuses_are_explicit_and_candidate_only_is_not_production_supported() -> None:
    dictionary = build_dictionary_v2(XML, release="RELEASE-202601")
    statuses = {candidate.status for candidate in dictionary.candidates}
    assert DictionaryStatus.CONTEXTUAL in statuses
    assert all(
        candidate.status is not DictionaryStatus.CANDIDATE_ONLY
        for candidate in dictionary.candidates
    )
    candidate = dictionary.candidates[0]
    assert (
        replace(candidate, status=DictionaryStatus.CANDIDATE_ONLY).status
        is DictionaryStatus.CANDIDATE_ONLY
    )


def test_free_variants_and_candidate_only_records_are_separate_statuses() -> None:
    xml = """
    <Wordlist>
      <Paradigm pdgId="1" lemma="вада" tag="N">
        <Variant id="a" lemma="вада" pravapis="A2008"><Form tag="NS">ва+да</Form></Variant>
      </Paradigm>
      <Paradigm pdgId="2" lemma="вада" tag="N">
        <Variant id="a" lemma="вада" pravapis="A2008"><Form tag="NS">вада+</Form></Variant>
      </Paradigm>
    </Wordlist>
    """
    dictionary = build_dictionary_v2(xml, release="test")

    assert dictionary.homographs[0].status is DictionaryStatus.FREE_VARIANT
    assert {item.lifecycle_status for item in dictionary.candidates} == {
        DictionaryStatus.CANDIDATE_ONLY
    }
    assert dict(dictionary.report.status_counts) == {"candidate_only": 2, "free_variant": 2}


def test_build_reports_every_rejected_schema_and_policy_case() -> None:
    xml = """
    <Wordlist>
      <Paradigm lemma="missing id"><Variant lemma="x"><Form tag="NS">во+да</Form></Variant></Paradigm>
      <Paradigm pdgId="2" lemma="missing variant lemma"><Variant><Form tag="NS">во+да</Form></Variant></Paradigm>
      <Paradigm pdgId="3" lemma="one" tag="N">
        <Variant lemma="one" pravapis="A2008"><Form tag="NS">до+м</Form></Variant>
      </Paradigm>
      <Paradigm pdgId="4" lemma="bad forms" tag="N">
        <Variant lemma="bad forms" pravapis="A2008">
          <Form tag="NS"></Form>
          <Form tag="NS" type="potential">во+да</Form>
          <Form tag="NS">в+ода</Form>
        </Variant>
      </Paradigm>
    </Wordlist>
    """
    report = build_dictionary_v2(xml, release="test").report

    assert report.invalid_paradigms == 1
    assert report.invalid_forms == 2
    assert dict(report.exclusion_counts) == {
        "invalid_paradigm": 1,
        "invalid_stress": 1,
        "invalid_variant": 1,
        "missing_form": 1,
        "not_a_homograph": 1,
        "unsupported_form_type": 1,
    }


def test_empty_form_orthography_does_not_inherit_variant_flag() -> None:
    xml = """
    <Wordlist><Paradigm pdgId="1" lemma="вада"><Variant lemma="вада" pravapis="A2008">
      <Form tag="NS" pravapis="">ва+да</Form>
    </Variant></Paradigm></Wordlist>
    """
    report = build_dictionary_v2(xml, release="test").report
    assert dict(report.exclusion_counts) == {"not_official_2008": 1}


def test_path_input_parse_errors_and_v1_identity_validation(tmp_path: Path) -> None:
    path = tmp_path / "grammar.xml"
    path.write_text(XML, encoding="utf-8")
    old = (
        DictionaryV1Identity("legacy-h", "legacy-a", "замак", "за́мак"),
        DictionaryV1Identity("legacy-h", "legacy-b", "замак", "зама́к"),
    )
    dictionary = build_dictionary_v2(path, release="test", v1_identities=old)
    assert dictionary.homographs[0].homograph_id == "legacy-h"
    assert {item.variant_id for item in dictionary.candidates} == {"legacy-a", "legacy-b"}
    assert (
        build_dictionary_v2(ET.fromstring(XML), release="test").logical_hash
        != dictionary.logical_hash
    )

    path.write_text("<Wordlist>", encoding="utf-8")
    with pytest.raises(GrammarDBParseError, match="invalid GrammarDB XML"):
        build_dictionary_v2(path, release="test")

    reused = (*old, DictionaryV1Identity("other-h", "legacy-a", "вада", "ва́да"))
    with pytest.raises(ValueError, match="variant ID is reused"):
        build_dictionary_v2(XML, release="test", v1_identities=reused)

    disagreeing = (*old, DictionaryV1Identity("other-h", "legacy-c", "замак", "замо́к"))
    with pytest.raises(ValueError, match="homograph IDs disagree"):
        build_dictionary_v2(XML, release="test", v1_identities=disagreeing)


def test_reviewed_conflicts_and_stratified_tail_are_deterministic() -> None:
    def paradigms(surface: str, start: int) -> str:
        first = surface[:2] + "+" + surface[2:]
        second = surface + "+"
        return (
            f"<Paradigm pdgId='{start}' lemma='{surface}' tag='N' meaning='one'>"
            f"<Variant lemma='{surface}' pravapis='A2008' slouniki='s'>"
            f"<Form tag='NS'>{first}</Form></Variant></Paradigm>"
            f"<Paradigm pdgId='{start + 1}' lemma='{surface}' tag='N' meaning='two'>"
            f"<Variant lemma='{surface}' pravapis='A2008' slouniki='s'>"
            f"<Form tag='NS'>{second}</Form></Variant></Paradigm>"
        )

    xml = (
        "<Wordlist>"
        + "".join(
            paradigms(surface, index * 10)
            for index, surface in enumerate(("вада", "рука", "нага", "гара"), start=1)
        )
        + "</Wordlist>"
    )
    dictionary = build_dictionary_v2(
        xml,
        release="test",
        status_overrides={"вада": DictionaryStatus.CONFLICT},
    )
    report = select_dictionary_qa_sample(
        dictionary,
        frequencies={"вада": 2000, "рука": 1500, "нага": 300, "гара": 5},
        tail_size=3,
        seed="qa-v1",
    )

    assert [item.official_surface for item in report.high_frequency_conflicts] == ["вада"]
    assert {item.frequency_band for item in report.tail_sample} == {"high", "medium", "low"}
    assert report == select_dictionary_qa_sample(
        dictionary,
        frequencies={"вада": 2000, "рука": 1500, "нага": 300, "гара": 5},
        tail_size=3,
        seed="qa-v1",
    )
    assert report.logical_hash

    with pytest.raises(ValueError, match="linguistic status"):
        build_dictionary_v2(
            xml,
            release="test",
            status_overrides={"вада": DictionaryStatus.PRODUCTION_SUPPORTED},
        )
    with pytest.raises(ValueError, match="unknown surfaces"):
        build_dictionary_v2(
            xml,
            release="test",
            status_overrides={"невядома": DictionaryStatus.CONFLICT},
        )
