from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from homograph_bel.dictionary.grammar_db import (
    GrammarDBParseError,
    GrammarDBSourceContract,
    build_dictionary_v2_from_archive,
    load_grammar_db_source_contract,
    verify_grammar_db_archive,
)


def _write_archive(path: Path) -> str:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "data/N.xml",
            "<Wordlist><Paradigm pdgId='1' lemma='вада' tag='N'><Variant id='a' lemma='вада' pravapis='A2008' slouniki='source'><Form tag='NS'>ва+да</Form></Variant></Paradigm></Wordlist>",
        )
        archive.writestr(
            "data/V.xml",
            "<Wordlist><Paradigm pdgId='2' lemma='вада' tag='N'><Variant id='a' lemma='вада' pravapis='A2008' slouniki='source'><Form tag='NS'>вада+</Form></Variant></Paradigm></Wordlist>",
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tracked_grammar_db_source_contract_is_pinned() -> None:
    contract = load_grammar_db_source_contract(Path("configs/dictionary/grammar-db-v2.toml"))

    assert contract.release == "RELEASE-202601"
    assert contract.asset_name == "RELEASE-202601.zip"
    assert contract.sha256 == "393756f3cb5c94ab86cdbd64b95fa9d096775f559ae65de6375ebb6d5571df00"
    assert contract.orthography == "A2008"
    assert len(contract.xml_members) == 17


def test_archive_checksum_members_and_cross_file_build(tmp_path: Path) -> None:
    path = tmp_path / "fixture.zip"
    digest = _write_archive(path)
    contract = GrammarDBSourceContract(
        release="test",
        asset_name="fixture.zip",
        url="https://example.invalid/fixture.zip",
        sha256=digest,
        orthography="A2008",
        xml_members=("N.xml", "V.xml"),
    )

    assert verify_grammar_db_archive(path, contract) == ("data/N.xml", "data/V.xml")
    dictionary = build_dictionary_v2_from_archive(path, contract)
    assert dictionary.report.homographs == 1
    assert dictionary.report.candidates == 2

    unsupported_contract = GrammarDBSourceContract(
        release=contract.release,
        asset_name=contract.asset_name,
        url=contract.url,
        sha256=contract.sha256,
        orthography="A1957",
        xml_members=contract.xml_members,
    )
    with pytest.raises(ValueError, match="A2008"):
        build_dictionary_v2_from_archive(path, unsupported_contract)

    bad_digest = GrammarDBSourceContract(
        release=contract.release,
        asset_name=contract.asset_name,
        url=contract.url,
        sha256="0" * 64,
        orthography=contract.orthography,
        xml_members=contract.xml_members,
    )
    with pytest.raises(ValueError, match="checksum"):
        verify_grammar_db_archive(path, bad_digest)


def test_source_contract_rejects_missing_members_and_fields(tmp_path: Path) -> None:
    path = tmp_path / "fixture.zip"
    digest = _write_archive(path)
    contract = GrammarDBSourceContract(
        release="test",
        asset_name="fixture.zip",
        url="https://example.invalid/fixture.zip",
        sha256=digest,
        orthography="A2008",
        xml_members=("missing.xml",),
    )
    with pytest.raises(ValueError, match="members"):
        verify_grammar_db_archive(path, contract)

    config = tmp_path / "bad.toml"
    config.write_text("release = 'test'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source contract"):
        load_grammar_db_source_contract(config)

    invalid_zip = tmp_path / "invalid.zip"
    invalid_zip.write_text("not a zip", encoding="utf-8")
    invalid_contract = GrammarDBSourceContract(
        release="test",
        asset_name="invalid.zip",
        url="https://example.invalid/invalid.zip",
        sha256=hashlib.sha256(invalid_zip.read_bytes()).hexdigest(),
        orthography="A2008",
        xml_members=(),
    )
    with pytest.raises(ValueError, match="valid ZIP"):
        verify_grammar_db_archive(invalid_zip, invalid_contract)

    wrong_root = tmp_path / "wrong.zip"
    with ZipFile(wrong_root, "w") as archive:
        archive.writestr("Other.xml", "<Other />")
    wrong_contract = GrammarDBSourceContract(
        release="test",
        asset_name="wrong.zip",
        url="https://example.invalid/wrong.zip",
        sha256=hashlib.sha256(wrong_root.read_bytes()).hexdigest(),
        orthography="A2008",
        xml_members=("Other.xml",),
    )
    with pytest.raises(GrammarDBParseError, match="not a Wordlist"):
        build_dictionary_v2_from_archive(wrong_root, wrong_contract)

    edge = tmp_path / "edge.zip"
    with ZipFile(edge, "w") as archive:
        archive.writestr(
            "Cases.xml",
            """
            <Wordlist>
              <Paradigm lemma="missing id"><Variant lemma="x"><Form tag="NS">во+да</Form></Variant></Paradigm>
              <Paradigm pdgId="2" lemma="bad variant"><Variant><Form tag="NS">во+да</Form></Variant></Paradigm>
              <Paradigm pdgId="3" lemma="single" tag="N"><Variant lemma="single" pravapis="A2008"><Form tag="NS">до+м</Form></Variant></Paradigm>
              <Paradigm pdgId="4" lemma="invalid form" tag="N"><Variant lemma="invalid form" pravapis="A2008"><Form tag="NS">вода</Form></Variant></Paradigm>
            </Wordlist>
            """,
        )
    edge_contract = GrammarDBSourceContract(
        release="test",
        asset_name="edge.zip",
        url="https://example.invalid/edge.zip",
        sha256=hashlib.sha256(edge.read_bytes()).hexdigest(),
        orthography="A2008",
        xml_members=("Cases.xml",),
    )
    report = build_dictionary_v2_from_archive(edge, edge_contract).report
    assert report.invalid_paradigms == 1
    assert report.invalid_forms == 1
    assert dict(report.exclusion_counts) == {
        "invalid_paradigm": 1,
        "invalid_stress": 1,
        "invalid_variant": 1,
        "not_a_homograph": 1,
    }
