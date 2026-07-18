"""Deterministic coverage statistics for a loaded Dictionary v2 index."""

from __future__ import annotations

from collections import Counter

from homograph_bel.dictionary.index import DictionaryIndex
from homograph_bel.dictionary.morphology import decode_grammar_db_analysis


def dictionary_statistics(index: DictionaryIndex) -> dict[str, object]:
    """Return a JSON-safe summary of options, statuses, and morphology evidence."""

    homographs = index.list_homographs()
    option_counts = [len(item.candidates) for item in homographs]
    lifecycle_counts: Counter[str] = Counter()
    pos_counts: Counter[str] = Counter()
    candidate_total = 0
    analysis_total = 0
    decoded_total = 0
    meaning_total = 0
    for homograph in homographs:
        for candidate in homograph.candidates:
            candidate_total += 1
            lifecycle_counts[str(candidate.lifecycle_status)] += 1
            for analysis in candidate.analyses:
                analysis_total += 1
                decoded = decode_grammar_db_analysis(analysis)
                decoded_total += decoded.decoded
                meaning_total += decoded.meaning is not None
                pos_counts[decoded.pos] += 1
    return {
        "release": index.release,
        "homographs": {
            "total": len(homographs),
            "by_status": dict(Counter(str(item.status) for item in homographs)),
            "by_candidate_count": {
                str(count): total for count, total in Counter(option_counts).items()
            },
        },
        "candidates": {
            "total": candidate_total,
            "average_per_homograph": round(candidate_total / len(homographs), 4),
            "maximum_per_homograph": max(option_counts),
            "by_lifecycle_status": dict(lifecycle_counts),
        },
        "analyses": {
            "total": analysis_total,
            "decoded": decoded_total,
            "with_meaning": meaning_total,
            "by_pos": dict(pos_counts),
        },
    }


__all__ = ["dictionary_statistics"]
