"""Command line for browsing and applying the Belarusian homograph dictionary."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

from homograph_bel.dictionary.index import DictionaryBundleError, DictionaryIndex
from homograph_bel.dictionary.v2 import DictionaryStatus
from homograph_bel.inference.dictionary import (
    HomographOccurrence,
    HomographScanner,
    PromptContractError,
    build_adjudication_prompt,
    build_lean_adjudication_prompt,
    parse_lean_adjudication_response,
)
from homograph_bel.resources import bundled_dictionary_index, bundled_dictionary_path


def main(argv: Sequence[str] | None = None) -> int:
    """Run the homograph-bel command line."""

    values = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="homograph-bel")
    commands = parser.add_subparsers(dest="command", required=True)
    dictionary = commands.add_parser("dictionary", help="browse and scan Dictionary v2")
    _add_dictionary_commands(dictionary)
    arguments = parser.parse_args(values)
    try:
        return _run_dictionary(arguments)
    except (DictionaryBundleError, PromptContractError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _add_dictionary_commands(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="dictionary_command", required=True)

    path = commands.add_parser("path", help="materialize and print the bundled dictionary path")
    path.add_argument("--cache-root", type=Path)

    list_command = commands.add_parser("list", help="list homograph surfaces")
    _add_bundle(list_command)
    list_command.add_argument(
        "--status",
        choices=[
            DictionaryStatus.CONTEXTUAL.value,
            DictionaryStatus.FREE_VARIANT.value,
            DictionaryStatus.CONFLICT.value,
        ],
    )
    list_command.add_argument("--limit", type=_positive_integer)

    show = commands.add_parser("show", help="show one homograph and its evidence")
    show.add_argument("surface")
    _add_bundle(show)

    detect = commands.add_parser("detect", help="detect all homographs in text")
    _add_bundle(detect)
    source = detect.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--input", type=Path)

    prompt = commands.add_parser("prompt", help="prepare a constrained LLM prompt")
    _add_bundle(prompt)
    prompt.add_argument("--text", required=True)
    prompt.add_argument("--occurrence", type=_positive_integer, default=1)
    prompt.add_argument("--profile", choices=("full", "lean"), default="full")
    prompt.add_argument("--morphology", help="caller morphology as a JSON object")
    prompt.add_argument("--example", action="append", default=[])
    prompt.add_argument("--response", help="parse a choice-only lean model response")


def _add_bundle(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--bundle", type=Path, help="use an unpacked Dictionary v2 bundle")
    source.add_argument("--cache-root", type=Path, help="override the bundled dictionary cache")


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _run_dictionary(arguments: argparse.Namespace) -> int:
    command = cast(str, arguments.dictionary_command)
    if command == "path":
        print(bundled_dictionary_path(arguments.cache_root))
        return 0
    index = _dictionary_index(arguments)
    if command == "list":
        status = DictionaryStatus(arguments.status) if arguments.status is not None else None
        for item in index.list_homographs(status=status, limit=arguments.limit):
            spellings = " | ".join(candidate.official_stressed for candidate in item.candidates)
            print(f"{item.official_surface}\t{item.status}\t{item.homograph_id}\t{spellings}")
        return 0
    if command == "show":
        item = index.get_homograph(arguments.surface)
        if item is None:
            raise ValueError(f"homograph not found: {arguments.surface}")
        _print_json(asdict(item), pretty=True)
        return 0

    scanner = HomographScanner(index)
    if command == "detect":
        for sentence_index, text in _input_texts(arguments):
            for occurrence_index, occurrence in enumerate(scanner.scan(text), start=1):
                _print_json(_occurrence_record(occurrence, sentence_index, occurrence_index))
        return 0
    assert command == "prompt"
    occurrences = scanner.scan(arguments.text)
    occurrence_number = cast(int, arguments.occurrence)
    if occurrence_number > len(occurrences):
        raise ValueError(f"occurrence {occurrence_number} not found in text")
    occurrence = occurrences[occurrence_number - 1]
    if arguments.profile == "lean":
        if arguments.morphology is not None or arguments.example:
            raise ValueError("morphology and examples require the full profile")
        prepared = build_lean_adjudication_prompt(occurrence)
        if arguments.response is not None:
            parsed = parse_lean_adjudication_response(prepared, arguments.response)
            _print_json(
                {
                    "response_status": parsed.status,
                    "selected_candidate_id": parsed.selected_candidate_id,
                    "possible_analyses": [asdict(item) for item in parsed.possible_analyses],
                    "raw_response": parsed.raw_response,
                },
                pretty=True,
            )
        else:
            _print_json(
                {
                    "prompt_version": prepared.version,
                    "decoder_version": prepared.decoder_version,
                    "prompt_hash": prepared.prompt_hash,
                    "system_prompt": prepared.system_prompt,
                    "user_prompt": prepared.user_prompt,
                    "candidate_ids": prepared.candidate_ids,
                },
                pretty=True,
            )
        return 0
    if arguments.response is not None:
        raise ValueError("response parsing requires the lean profile")
    morphology = _parse_morphology(arguments.morphology)
    result = build_adjudication_prompt(
        occurrence,
        observed_morphology=morphology,
        examples=tuple(arguments.example),
    )
    _print_json(
        {
            "prompt_version": result.version,
            "prompt_hash": result.prompt_hash,
            "prompt": result.prompt,
        },
        pretty=True,
    )
    return 0


def _dictionary_index(arguments: argparse.Namespace) -> DictionaryIndex:
    bundle = cast(Path | None, arguments.bundle)
    if bundle is not None:
        return DictionaryIndex.from_bundle(bundle)
    return bundled_dictionary_index(cast(Path | None, arguments.cache_root))


def _input_texts(arguments: argparse.Namespace) -> Iterator[tuple[int, str]]:
    if arguments.text is not None:
        yield 1, cast(str, arguments.text)
        return
    path = cast(Path, arguments.input)
    with path.open(encoding="utf-8") as stream:
        for sentence_index, line in enumerate(stream, start=1):
            yield sentence_index, line.rstrip("\r\n")


def _occurrence_record(
    occurrence: HomographOccurrence, sentence_index: int, occurrence_index: int
) -> dict[str, object]:
    return {
        "sentence_index": sentence_index,
        "occurrence_index": occurrence_index,
        "text": occurrence.text,
        "target_surface": occurrence.target_surface,
        "target_normalized": occurrence.target_normalized,
        "target_start": occurrence.target_start,
        "target_end": occurrence.target_end,
        "homograph_id": occurrence.homograph_id,
        "dictionary_version": occurrence.dictionary_version,
        "status": occurrence.status,
        "candidate_ids": occurrence.candidate_ids,
        "candidates": [
            {
                "variant_id": candidate.variant_id,
                "official_stressed": candidate.official_stressed,
                "stress_position": candidate.stress_position,
                "status": candidate.status,
                "lifecycle_status": candidate.lifecycle_status,
            }
            for candidate in occurrence.homograph.candidates
        ],
    }


def _parse_morphology(raw: str | None) -> Mapping[str, str] | None:
    if raw is None:
        return None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("morphology must be a JSON object")
    return cast(dict[str, str], value)


def _print_json(value: object, *, pretty: bool = False) -> None:
    separators = None if pretty else (",", ":")
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if pretty else None,
            separators=separators,
        )
    )


__all__ = ["main"]
