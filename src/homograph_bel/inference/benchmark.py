"""Reproducible performance benchmark for dictionary text scanning."""

from __future__ import annotations

import time
from itertools import repeat
from pathlib import Path

from homograph_bel.dictionary.index import DictionaryIndex
from homograph_bel.inference.dictionary import WORD_PATTERN, HomographScanner


def run_benchmark(bundle: Path, *, sentences: int = 100_000) -> dict[str, int | float | str]:
    """Load one bundle, stream synthetic sentences, and return measured throughput."""

    if sentences < 1:
        raise ValueError("sentences must be positive")
    load_started = time.perf_counter()
    index = DictionaryIndex.from_bundle(bundle)
    index_load_seconds = time.perf_counter() - load_started
    first = index.list_homographs(limit=1)
    if not first:
        raise ValueError("dictionary contains no homographs")
    surface = first[0].official_surface
    sentence = f"Гэта {surface} ў тэставым сказе."
    tokens_per_sentence = sum(1 for _ in WORD_PATTERN.finditer(sentence))

    scanner = HomographScanner(index)
    scan_started = time.perf_counter()
    occurrences = sum(len(batch) for batch in scanner.scan_many(repeat(sentence, sentences)))
    scan_seconds = time.perf_counter() - scan_started
    if occurrences != sentences:
        raise RuntimeError(f"benchmark expected {sentences} occurrences but detected {occurrences}")
    tokens = tokens_per_sentence * sentences
    return {
        "dictionary_homographs": len(index),
        "surface": surface,
        "sentences": sentences,
        "tokens": tokens,
        "occurrences": occurrences,
        "index_load_seconds": index_load_seconds,
        "scan_seconds": scan_seconds,
        "sentences_per_second": sentences / scan_seconds,
        "tokens_per_second": tokens / scan_seconds,
        "occurrences_per_second": occurrences / scan_seconds,
    }


__all__ = ["run_benchmark"]
