from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from homograph_bel.dictionary.index import DictionaryBundleError, DictionaryIndex
from homograph_bel.dictionary.output import write_dictionary_v2_bundle
from homograph_bel.dictionary.v2 import DictionaryStatus, build_dictionary_v2


def _write_bundle(path: Path) -> Path:
    dictionary = build_dictionary_v2(
        """
        <Wordlist>
          <Paradigm pdgId="1" lemma="аб'ява" tag="" meaning="quantity">
            <Variant id="a" lemma="аб'ява" pravapis="A2008" slouniki="source-a">
              <Form tag="" slouniki="source-a">аб'я+ва</Form>
            </Variant>
          </Paradigm>
          <Paradigm pdgId="2" lemma="аб'ява" tag="V" meaning="go around">
            <Variant id="a" lemma="аб'ява" pravapis="A2008" slouniki="source-b">
              <Form tag="V1" slouniki="source-b">аб'ява+</Form>
            </Variant>
          </Paradigm>
          <Paradigm pdgId="3" lemma="вада" tag="N" meaning="water">
            <Variant id="a" lemma="вада" pravapis="A2008" slouniki="source-c">
              <Form tag="NS">ва+да</Form>
            </Variant>
          </Paradigm>
          <Paradigm pdgId="4" lemma="вада" tag="N" meaning="water variant">
            <Variant id="a" lemma="вада" pravapis="A2008" slouniki="source-d">
              <Form tag="NS">вада+</Form>
            </Variant>
          </Paradigm>
        </Wordlist>
        """,
        release="test-release",
        status_overrides={
            "аб'ява": DictionaryStatus.CONTEXTUAL,
            "вада": DictionaryStatus.FREE_VARIANT,
        },
    )
    write_dictionary_v2_bundle(path, dictionary)
    return path


def _rehash(path: Path, name: str) -> None:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][name] = hashlib.sha256((path / name).read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _rows(path: Path, name: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in (path / name).read_text().splitlines()]


def _write_rows(path: Path, name: str, rows: list[dict[str, object]]) -> None:
    (path / name).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    _rehash(path, name)


def test_loads_and_joins_a_valid_dictionary_bundle(tmp_path: Path) -> None:
    index = DictionaryIndex.from_bundle(_write_bundle(tmp_path))

    assert index.release == "test-release"
    assert len(index) == 2
    item = index.get_homograph("АБʼЯВА")
    assert item is not None
    assert item.official_surface == "аб'ява"
    assert item.status is DictionaryStatus.CONTEXTUAL
    assert len(item.candidates) == 2
    assert {
        analysis.meaning for candidate in item.candidates for analysis in candidate.analyses
    } == {
        "quantity",
        "go around",
    }
    assert all(candidate.provenance for candidate in item.candidates)


def test_lists_homographs_deterministically_with_filters(tmp_path: Path) -> None:
    index = DictionaryIndex.from_bundle(_write_bundle(tmp_path))

    assert [item.official_surface for item in index.list_homographs()] == ["аб'ява", "вада"]
    assert [
        item.official_surface
        for item in index.list_homographs(status=DictionaryStatus.FREE_VARIANT)
    ] == ["вада"]
    assert [item.official_surface for item in index.list_homographs(limit=1)] == ["аб'ява"]
    with pytest.raises(ValueError, match="positive"):
        index.list_homographs(limit=0)


def test_rejects_a_bundle_with_a_changed_file(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    with (bundle / "homographs.jsonl").open("a") as stream:
        stream.write("{}\n")

    with pytest.raises(DictionaryBundleError, match=r"hash mismatch.*homographs\.jsonl"):
        DictionaryIndex.from_bundle(bundle)


def test_rejects_missing_malformed_and_dangling_bundle_records(tmp_path: Path) -> None:
    with pytest.raises(DictionaryBundleError, match=r"manifest\.json"):
        DictionaryIndex.from_bundle(tmp_path)

    bundle = _write_bundle(tmp_path)
    (bundle / "analyses.jsonl").write_text("not-json\n")
    _rehash(bundle, "analyses.jsonl")
    with pytest.raises(DictionaryBundleError, match=r"analyses\.jsonl:1.*JSON"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "dangling")
    candidate_path = bundle / "candidates.jsonl"
    rows = [json.loads(line) for line in candidate_path.read_text().splitlines()]
    dangling_variant = rows[0]["variant_id"]
    rows[0]["homograph_id"] = "missing-homograph"
    candidate_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    _rehash(bundle, "candidates.jsonl")
    analyses = _rows(bundle, "analyses.jsonl")
    for analysis in analyses:
        if analysis["variant_id"] == dangling_variant:
            analysis["homograph_id"] = "missing-homograph"
    _write_rows(bundle, "analyses.jsonl", analyses)
    with pytest.raises(DictionaryBundleError, match="dangling homograph_id"):
        DictionaryIndex.from_bundle(bundle)


def test_rejects_duplicate_ids_and_inconsistent_surfaces(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    homographs_path = bundle / "homographs.jsonl"
    first = homographs_path.read_text().splitlines()[0]
    with homographs_path.open("a") as stream:
        stream.write(first + "\n")
    _rehash(bundle, "homographs.jsonl")
    with pytest.raises(DictionaryBundleError, match="duplicate homograph_id"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "surface")
    candidate_path = bundle / "candidates.jsonl"
    rows = [json.loads(line) for line in candidate_path.read_text().splitlines()]
    rows[0]["official_surface"] = "іншае"
    candidate_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    _rehash(bundle, "candidates.jsonl")
    with pytest.raises(DictionaryBundleError, match="candidate surface"):
        DictionaryIndex.from_bundle(bundle)


def test_accepts_empty_grammar_source_tags_emitted_by_dictionary_v2(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    item = DictionaryIndex.from_bundle(bundle).get_homograph("аб'ява")
    assert item is not None
    analysis = next(
        analysis
        for candidate in item.candidates
        for analysis in candidate.analyses
        if analysis.form_tag == ""
    )
    assert analysis.pos == ""
    assert analysis.paradigm_tag == ""
    assert analysis.form_tag == ""


def test_rejects_invalid_manifest_shapes_and_missing_tables(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "not-object")
    (bundle / "manifest.json").write_text("[]")
    with pytest.raises(DictionaryBundleError, match="dictionary-v2 object"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "schema")
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["schema_version"] = "other"
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(DictionaryBundleError, match="dictionary-v2 object"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "files")
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["files"] = []
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(DictionaryBundleError, match="files must be an object"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "release")
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["release"] = ""
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(DictionaryBundleError, match="release must be a non-empty string"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "missing-table")
    (bundle / "candidates.jsonl").unlink()
    with pytest.raises(DictionaryBundleError, match=r"cannot read candidates\.jsonl"):
        DictionaryIndex.from_bundle(bundle)


def test_rejects_non_object_jsonl_and_duplicate_variant_ids(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "json-array")
    (bundle / "analyses.jsonl").write_text("[]\n")
    _rehash(bundle, "analyses.jsonl")
    with pytest.raises(DictionaryBundleError, match="JSON object"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "duplicate-variant")
    candidates = _rows(bundle, "candidates.jsonl")
    candidates.append(deepcopy(candidates[0]))
    _write_rows(bundle, "candidates.jsonl", candidates)
    with pytest.raises(DictionaryBundleError, match="duplicate variant_id"):
        DictionaryIndex.from_bundle(bundle)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("form_tag", 1, "form_tag must be a string"),
        ("meaning", 1, "meaning must be a string or null"),
        ("morphology", "bad", "morphology must be a list of strings"),
        ("morphology", [1], "morphology must be a list of strings"),
    ],
)
def test_rejects_invalid_analysis_field_types(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    bundle = _write_bundle(tmp_path / f"bad-{field}-{type(value).__name__}")
    analyses = _rows(bundle, "analyses.jsonl")
    analyses[0][field] = value
    _write_rows(bundle, "analyses.jsonl", analyses)

    with pytest.raises(DictionaryBundleError, match=message):
        DictionaryIndex.from_bundle(bundle)


def test_rejects_invalid_candidate_and_homograph_links(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "stress-position")
    candidates = _rows(bundle, "candidates.jsonl")
    candidates[0]["stress_position"] = "zero"
    _write_rows(bundle, "candidates.jsonl", candidates)
    with pytest.raises(DictionaryBundleError, match="stress_position must be an integer"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "unknown-candidate")
    homographs = _rows(bundle, "homographs.jsonl")
    homographs[0]["candidate_ids"] = ["unknown", *homographs[0]["candidate_ids"][1:]]  # type: ignore[index]
    _write_rows(bundle, "homographs.jsonl", homographs)
    with pytest.raises(DictionaryBundleError, match="invalid homograph"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "one-candidate")
    homographs = _rows(bundle, "homographs.jsonl")
    homographs[0]["candidate_ids"] = homographs[0]["candidate_ids"][:1]  # type: ignore[index]
    _write_rows(bundle, "homographs.jsonl", homographs)
    with pytest.raises(DictionaryBundleError, match="at least two candidates"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "wrong-owner")
    homographs = _rows(bundle, "homographs.jsonl")
    candidates = _rows(bundle, "candidates.jsonl")
    moved_variant = candidates[0]["variant_id"]
    candidates[0]["homograph_id"] = homographs[1]["homograph_id"]
    _write_rows(bundle, "candidates.jsonl", candidates)
    analyses = _rows(bundle, "analyses.jsonl")
    for analysis in analyses:
        if analysis["variant_id"] == moved_variant:
            analysis["homograph_id"] = homographs[1]["homograph_id"]
    _write_rows(bundle, "analyses.jsonl", analyses)
    with pytest.raises(DictionaryBundleError, match="belongs to another homograph"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "version")
    homographs = _rows(bundle, "homographs.jsonl")
    homographs[0]["dictionary_version"] = "other-release"
    _write_rows(bundle, "homographs.jsonl", homographs)
    with pytest.raises(DictionaryBundleError, match="version differs"):
        DictionaryIndex.from_bundle(bundle)


def test_rejects_duplicate_normalized_surfaces(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    homographs = _rows(bundle, "homographs.jsonl")
    candidates = _rows(bundle, "candidates.jsonl")
    analyses = _rows(bundle, "analyses.jsonl")
    duplicate = deepcopy(homographs[0])
    duplicate["homograph_id"] = "duplicate-homograph"
    duplicate_ids: list[str] = []
    original_ids = duplicate["candidate_ids"]
    assert isinstance(original_ids, list)
    assert all(isinstance(item, str) for item in cast(list[object], original_ids))
    for original_id in cast(list[str], original_ids):
        original = next(item for item in candidates if item["variant_id"] == original_id)
        copied = deepcopy(original)
        copied["variant_id"] = f"{original_id}-copy"
        copied["homograph_id"] = "duplicate-homograph"
        copied_provenance: list[str] = []
        for source_analysis in [item for item in analyses if item["variant_id"] == original_id]:
            copied_analysis = deepcopy(source_analysis)
            copied_analysis["variant_id"] = f"{original_id}-copy"
            copied_analysis["homograph_id"] = "duplicate-homograph"
            copied_analysis["source_form_id"] = f"{source_analysis['source_form_id']}-copy"
            copied_analysis["analysis_id"] = (
                f"{copied_analysis['release']}:{copied_analysis['source_paradigm_id']}:"
                f"{copied_analysis['source_variant_id']}:"
                f"{copied_analysis['source_form_id']}"
            )
            copied_provenance.append(copied_analysis["analysis_id"])
            analyses.append(copied_analysis)
        copied["provenance"] = copied_provenance
        candidates.append(copied)
        duplicate_ids.append(f"{original_id}-copy")
    duplicate["candidate_ids"] = duplicate_ids
    homographs.append(duplicate)
    _write_rows(bundle, "analyses.jsonl", analyses)
    _write_rows(bundle, "candidates.jsonl", candidates)
    _write_rows(bundle, "homographs.jsonl", homographs)

    with pytest.raises(DictionaryBundleError, match="duplicate normalized homograph surface"):
        DictionaryIndex.from_bundle(bundle)


def test_validates_all_manifest_file_hashes_and_logical_hash(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "logical")
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["logical_hash"] = "0" * 64
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(DictionaryBundleError, match="logical hash mismatch"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "report")
    with (bundle / "build-report.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(DictionaryBundleError, match=r"hash mismatch.*build-report\.json"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "unsafe-name")
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["files"]["../outside"] = "0" * 64
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(DictionaryBundleError, match="unsafe manifest filename"):
        DictionaryIndex.from_bundle(bundle)


def test_rejects_invalid_analysis_identity_and_references(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "analysis-id")
    analyses = _rows(bundle, "analyses.jsonl")
    analyses[0]["analysis_id"] = "wrong"
    _write_rows(bundle, "analyses.jsonl", analyses)
    with pytest.raises(DictionaryBundleError, match="analysis_id differs"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "duplicate-analysis")
    analyses = _rows(bundle, "analyses.jsonl")
    analyses.append(deepcopy(analyses[0]))
    _write_rows(bundle, "analyses.jsonl", analyses)
    with pytest.raises(DictionaryBundleError, match="duplicate analysis_id"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "analysis-release")
    analyses = _rows(bundle, "analyses.jsonl")
    analyses[0]["release"] = "other-release"
    analyses[0]["analysis_id"] = str(analyses[0]["analysis_id"]).replace(
        "test-release", "other-release"
    )
    _write_rows(bundle, "analyses.jsonl", analyses)
    with pytest.raises(DictionaryBundleError, match="analysis release differs"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "unknown-analysis-variant")
    analyses = _rows(bundle, "analyses.jsonl")
    analyses[0]["variant_id"] = "unknown-variant"
    _write_rows(bundle, "analyses.jsonl", analyses)
    with pytest.raises(DictionaryBundleError, match="unknown variant_id"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "analysis-homograph")
    analyses = _rows(bundle, "analyses.jsonl")
    homographs = _rows(bundle, "homographs.jsonl")
    analyses[0]["homograph_id"] = homographs[1]["homograph_id"]
    _write_rows(bundle, "analyses.jsonl", analyses)
    with pytest.raises(DictionaryBundleError, match="analysis homograph_id"):
        DictionaryIndex.from_bundle(bundle)


def test_rejects_incomplete_or_duplicated_candidate_closure(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "duplicate-link")
    homographs = _rows(bundle, "homographs.jsonl")
    candidate_ids = homographs[0]["candidate_ids"]
    assert isinstance(candidate_ids, list)
    homographs[0]["candidate_ids"] = [candidate_ids[0], candidate_ids[0]]
    _write_rows(bundle, "homographs.jsonl", homographs)
    with pytest.raises(DictionaryBundleError, match="candidate_ids must be unique"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "zero-analysis")
    candidates = _rows(bundle, "candidates.jsonl")
    analyses = _rows(bundle, "analyses.jsonl")
    empty_variant = candidates[0]["variant_id"]
    analyses = [item for item in analyses if item["variant_id"] != empty_variant]
    _write_rows(bundle, "analyses.jsonl", analyses)
    with pytest.raises(DictionaryBundleError, match="must have at least one analysis"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "provenance")
    candidates = _rows(bundle, "candidates.jsonl")
    candidates[0]["provenance"] = ["wrong"]
    _write_rows(bundle, "candidates.jsonl", candidates)
    with pytest.raises(DictionaryBundleError, match="provenance differs"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "status")
    candidates = _rows(bundle, "candidates.jsonl")
    candidates[0]["status"] = "conflict"
    _write_rows(bundle, "candidates.jsonl", candidates)
    with pytest.raises(DictionaryBundleError, match="candidate status differs"):
        DictionaryIndex.from_bundle(bundle)


def test_rejects_statuses_outside_their_field_specific_domains(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path / "candidate-status")
    candidates = _rows(bundle, "candidates.jsonl")
    candidates[0]["status"] = "production_supported"
    _write_rows(bundle, "candidates.jsonl", candidates)
    with pytest.raises(DictionaryBundleError, match="candidate linguistic status"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "lifecycle-status")
    candidates = _rows(bundle, "candidates.jsonl")
    candidates[0]["lifecycle_status"] = "contextual"
    _write_rows(bundle, "candidates.jsonl", candidates)
    with pytest.raises(DictionaryBundleError, match="candidate lifecycle status"):
        DictionaryIndex.from_bundle(bundle)

    bundle = _write_bundle(tmp_path / "homograph-status")
    homographs = _rows(bundle, "homographs.jsonl")
    homographs[0]["status"] = "production_supported"
    _write_rows(bundle, "homographs.jsonl", homographs)
    with pytest.raises(DictionaryBundleError, match="homograph linguistic status"):
        DictionaryIndex.from_bundle(bundle)


def test_rejects_candidate_rows_omitted_from_homograph_links(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    candidates = _rows(bundle, "candidates.jsonl")
    analyses = _rows(bundle, "analyses.jsonl")
    copied_candidate = deepcopy(candidates[0])
    copied_candidate["variant_id"] = "unlinked-variant"
    copied_analysis = deepcopy(analyses[0])
    copied_analysis["variant_id"] = "unlinked-variant"
    copied_analysis["source_form_id"] = "999"
    copied_analysis["analysis_id"] = (
        f"{copied_analysis['release']}:{copied_analysis['source_paradigm_id']}:"
        f"{copied_analysis['source_variant_id']}:999"
    )
    copied_candidate["provenance"] = [copied_analysis["analysis_id"]]
    candidates.append(copied_candidate)
    analyses.append(copied_analysis)
    _write_rows(bundle, "candidates.jsonl", candidates)
    _write_rows(bundle, "analyses.jsonl", analyses)

    with pytest.raises(DictionaryBundleError, match="not linked by homographs"):
        DictionaryIndex.from_bundle(bundle)
