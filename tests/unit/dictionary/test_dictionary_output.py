from __future__ import annotations

import json
from pathlib import Path

from homograph_bel.dictionary.grammar_db import (
    DictionaryV1Identity,
    build_dictionary_v2,
    migrate_dictionary_v1_ids,
    select_dictionary_qa_sample,
)
from homograph_bel.dictionary.output import write_dictionary_v2_bundle


def test_dictionary_bundle_emits_versioned_linked_tables_and_reports(tmp_path: Path) -> None:
    xml = """
    <Wordlist>
      <Paradigm pdgId="1" lemma="вада" tag="N" meaning="one">
        <Variant id="a" lemma="вада" pravapis="A2008" slouniki="s">
          <Form tag="NS">ва+да</Form>
        </Variant>
      </Paradigm>
      <Paradigm pdgId="2" lemma="вада" tag="N" meaning="two">
        <Variant id="a" lemma="вада" pravapis="A2008" slouniki="s">
          <Form tag="NS">вада+</Form>
        </Variant>
      </Paradigm>
    </Wordlist>
    """
    dictionary = build_dictionary_v2(xml, release="test")
    migration = migrate_dictionary_v1_ids(
        (DictionaryV1Identity("old-h", "old-v", "вада", "ва́да"),),
        dictionary,
    )
    qa = select_dictionary_qa_sample(
        dictionary,
        frequencies={"вада": 100},
        tail_size=1,
        seed="test",
    )

    manifest = write_dictionary_v2_bundle(tmp_path, dictionary, migration=migration, qa=qa)
    first_bytes = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    repeated = write_dictionary_v2_bundle(tmp_path, dictionary, migration=migration, qa=qa)

    assert manifest == repeated
    assert first_bytes == {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert set(manifest["files"]) == {
        "analyses.jsonl",
        "build-report.json",
        "candidates.jsonl",
        "homographs.jsonl",
        "migration-report.json",
        "qa-report.json",
    }
    candidates = [
        json.loads(line) for line in (tmp_path / "candidates.jsonl").read_text().splitlines()
    ]
    analyses = [json.loads(line) for line in (tmp_path / "analyses.jsonl").read_text().splitlines()]
    assert len(candidates) == 2
    assert {item["variant_id"] for item in analyses} == {item["variant_id"] for item in candidates}
    assert (
        json.loads((tmp_path / "manifest.json").read_text())["logical_hash"]
        == dictionary.logical_hash
    )
