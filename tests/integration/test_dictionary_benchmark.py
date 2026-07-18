from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast

import pytest

from homograph_bel.dictionary.output import write_dictionary_v2_bundle
from homograph_bel.dictionary.v2 import build_dictionary_v2
from homograph_bel.inference.benchmark import run_benchmark
from homograph_bel.inference.dictionary import HomographOccurrence, HomographScanner


def test_benchmark_counts_streamed_sentences_tokens_and_occurrences(tmp_path: Path) -> None:
    dictionary = build_dictionary_v2(
        """
        <Wordlist>
          <Paradigm pdgId="1" lemma="вада" tag="N">
            <Variant id="a" lemma="вада" pravapis="A2008" slouniki="a">
              <Form tag="NS">ва+да</Form>
            </Variant>
          </Paradigm>
          <Paradigm pdgId="2" lemma="вада" tag="V">
            <Variant id="a" lemma="вада" pravapis="A2008" slouniki="b">
              <Form tag="V2">вада+</Form>
            </Variant>
          </Paradigm>
        </Wordlist>
        """,
        release="test-release",
    )
    write_dictionary_v2_bundle(tmp_path, dictionary)

    result = run_benchmark(tmp_path, sentences=3)

    assert result["sentences"] == 3
    assert result["occurrences"] == 3
    assert result["tokens"] == 15
    assert result["dictionary_homographs"] == 1
    assert cast(float, result["index_load_seconds"]) >= 0
    assert cast(float, result["scan_seconds"]) > 0
    assert cast(float, result["sentences_per_second"]) > 0
    assert cast(float, result["tokens_per_second"]) > 0
    assert cast(float, result["occurrences_per_second"]) > 0


def test_benchmark_rejects_invalid_counts_and_empty_dictionaries(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        run_benchmark(tmp_path, sentences=0)

    empty = build_dictionary_v2("<Wordlist />", release="empty")
    write_dictionary_v2_bundle(tmp_path, empty)
    with pytest.raises(ValueError, match="no homographs"):
        run_benchmark(tmp_path, sentences=1)


def test_benchmark_fails_if_the_scanner_misses_expected_occurrences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dictionary = build_dictionary_v2(
        """
        <Wordlist>
          <Paradigm pdgId="1" lemma="вада" tag="N">
            <Variant id="a" lemma="вада" pravapis="A2008"><Form tag="N">ва+да</Form></Variant>
          </Paradigm>
          <Paradigm pdgId="2" lemma="вада" tag="V">
            <Variant id="a" lemma="вада" pravapis="A2008"><Form tag="V">вада+</Form></Variant>
          </Paradigm>
        </Wordlist>
        """,
        release="test-release",
    )
    write_dictionary_v2_bundle(tmp_path, dictionary)

    def no_matches(
        _scanner: HomographScanner, texts: Iterable[str]
    ) -> Iterator[tuple[HomographOccurrence, ...]]:
        for _text in texts:
            yield ()

    monkeypatch.setattr(HomographScanner, "scan_many", no_matches)
    with pytest.raises(RuntimeError, match="expected 2 occurrences but detected 0"):
        run_benchmark(tmp_path, sentences=2)
