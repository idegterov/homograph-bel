from __future__ import annotations

import json
from pathlib import Path

import pytest

from homograph_bel.cli import main
from homograph_bel.dictionary.output import write_dictionary_v2_bundle
from homograph_bel.dictionary.v2 import build_dictionary_v2


def _bundle(path: Path) -> Path:
    dictionary = build_dictionary_v2(
        """
        <Wordlist>
          <Paradigm pdgId="1" lemma="вада" tag="N" meaning="substance">
            <Variant id="a" lemma="вада" pravapis="A2008" slouniki="dictionary-a">
              <Morph>Case=Nom|Number=Sing</Morph>
              <Form tag="NS">ва+да</Form>
            </Variant>
          </Paradigm>
          <Paradigm pdgId="2" lemma="вада" tag="V" meaning="action">
            <Variant id="a" lemma="вада" pravapis="A2008" slouniki="dictionary-b">
              <Morph>Person=2|Number=Sing</Morph>
              <Form tag="V2">вада+</Form>
            </Variant>
          </Paradigm>
        </Wordlist>
        """,
        release="test-release",
    )
    write_dictionary_v2_bundle(path, dictionary)
    return path


def test_cli_lists_and_shows_homographs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bundle = _bundle(tmp_path)

    assert main(["dictionary", "list", "--bundle", str(bundle)]) == 0
    listed = capsys.readouterr().out
    assert "вада\tcontextual\t" in listed
    assert "ва́да" in listed
    assert "вада́" in listed

    assert main(["dictionary", "show", "вада", "--bundle", str(bundle)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["official_surface"] == "вада"
    assert shown["dictionary_version"] == "test-release"
    assert len(shown["candidates"]) == 2
    assert shown["candidates"][0]["analyses"][0]["morphology"]


def test_cli_detects_text_and_streams_input_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _bundle(tmp_path / "bundle")

    assert (
        main(
            [
                "dictionary",
                "detect",
                "--bundle",
                str(bundle),
                "--text",
                "Вада, не вадавада, і вада.",
            ]
        )
        == 0
    )
    detected = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [item["target_surface"] for item in detected] == ["Вада", "вада"]
    assert [item["occurrence_index"] for item in detected] == [1, 2]
    assert all(
        item["text"][item["target_start"] : item["target_end"]] == item["target_surface"]
        for item in detected
    )
    assert all(len(item["candidates"]) == 2 for item in detected)
    assert all("official_stressed" in candidate for candidate in detected[0]["candidates"])
    assert all("analyses" not in candidate for candidate in detected[0]["candidates"])

    source = tmp_path / "sentences.txt"
    source.write_text("Няма супадзення.\nТут вада.\n", encoding="utf-8")
    assert (
        main(
            [
                "dictionary",
                "detect",
                "--bundle",
                str(bundle),
                "--input",
                str(source),
            ]
        )
        == 0
    )
    streamed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(streamed) == 1
    assert streamed[0]["sentence_index"] == 2
    assert streamed[0]["text"] == "Тут вада."


def test_cli_prepares_prompt_with_optional_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _bundle(tmp_path)

    assert (
        main(
            [
                "dictionary",
                "prompt",
                "--bundle",
                str(bundle),
                "--text",
                "Вада і вада.",
                "--occurrence",
                "2",
                "--morphology",
                '{"Case":"Nom"}',
                "--example",
                "Правераны прыклад.",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["prompt_version"] == "homograph-adjudication-v1"
    assert len(result["prompt_hash"]) == 64
    assert "<target>вада</target>." in result["prompt"]
    assert '"Case":"Nom"' in result["prompt"]
    assert "Правераны прыклад." in result["prompt"]


def test_cli_prepares_and_parses_lean_prompt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _bundle(tmp_path)
    command = [
        "dictionary",
        "prompt",
        "--bundle",
        str(bundle),
        "--text",
        "Тут вада.",
        "--profile",
        "lean",
    ]

    assert main(command) == 0
    prompt = json.loads(capsys.readouterr().out)
    assert prompt["prompt_version"] == "homograph-lean-choice-v1"
    assert prompt["decoder_version"].startswith("grammardb-unimorph-")
    assert prompt["user_prompt"].splitlines()[0] == "Тут <t>вада</t>."
    assert "Case=Nom" in prompt["user_prompt"]
    assert len(prompt["candidate_ids"]) == 2
    assert all(
        candidate_id not in prompt["user_prompt"] for candidate_id in prompt["candidate_ids"]
    )

    assert main([*command, "--response", "2"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["response_status"] == "selected"
    assert parsed["selected_candidate_id"] == prompt["candidate_ids"][1]
    assert parsed["possible_analyses"][0]["pos"] == "NOUN"


def test_cli_rejects_lean_only_options_for_full_prompt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _bundle(tmp_path)

    assert (
        main(
            [
                "dictionary",
                "prompt",
                "--bundle",
                str(bundle),
                "--text",
                "Тут вада.",
                "--response",
                "1",
            ]
        )
        == 2
    )
    assert "lean profile" in capsys.readouterr().err

    assert (
        main(
            [
                "dictionary",
                "prompt",
                "--profile",
                "lean",
                "--bundle",
                str(bundle),
                "--text",
                "Тут вада.",
                "--morphology",
                '{"Case":"Nom"}',
            ]
        )
        == 2
    )
    assert "full profile" in capsys.readouterr().err


def test_cli_reports_missing_surfaces_and_occurrences(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _bundle(tmp_path)

    assert main(["dictionary", "show", "няма", "--bundle", str(bundle)]) == 2
    assert "not found" in capsys.readouterr().err
    assert (
        main(
            [
                "dictionary",
                "prompt",
                "--bundle",
                str(bundle),
                "--text",
                "Няма супадзення.",
            ]
        )
        == 2
    )
    assert "occurrence 1" in capsys.readouterr().err


def test_root_cli_exposes_bundled_dictionary_and_validates_arguments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["dictionary", "path", "--cache-root", str(tmp_path / "cache")]) == 0
    bundled_path = Path(capsys.readouterr().out.strip())
    assert bundled_path.name == "dictionary"
    assert (bundled_path / "manifest.json").is_file()

    assert (
        main(
            [
                "dictionary",
                "list",
                "--cache-root",
                str(tmp_path / "cache"),
                "--limit",
                "1",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out.strip()

    bundle = _bundle(tmp_path)
    with pytest.raises(SystemExit, match="2"):
        main(["dictionary", "list", "--bundle", str(bundle), "--limit", "0"])
    assert "positive" in capsys.readouterr().err

    with pytest.raises(SystemExit, match="2"):
        main(
            [
                "dictionary",
                "list",
                "--bundle",
                str(bundle),
                "--status",
                "production_supported",
            ]
        )
    assert "invalid choice" in capsys.readouterr().err


def test_cli_prompt_without_morphology_and_with_invalid_morphology(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = _bundle(tmp_path)
    base = [
        "dictionary",
        "prompt",
        "--bundle",
        str(bundle),
        "--text",
        "Тут вада.",
    ]

    assert main(base) == 0
    assert "Observed morphology" not in json.loads(capsys.readouterr().out)["prompt"]

    assert main([*base, "--morphology", "[]"]) == 2
    assert "JSON object" in capsys.readouterr().err
