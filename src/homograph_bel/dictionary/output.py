"""Deterministic, linked Dictionary v2 table and report output."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from homograph_bel.dictionary.v2 import (
    DictionaryMigrationReport,
    DictionaryQAReport,
    DictionaryV2,
)

type Manifest = dict[str, str | dict[str, str]]


def write_dictionary_v2_bundle(
    output_dir: Path,
    dictionary: DictionaryV2,
    *,
    migration: DictionaryMigrationReport | None = None,
    qa: DictionaryQAReport | None = None,
) -> Manifest:
    """Write deterministic identity, candidate, analysis, and audit files."""

    output_dir.mkdir(parents=True, exist_ok=True)
    homographs = [
        {
            "homograph_id": item.homograph_id,
            "official_surface": item.official_surface,
            "dictionary_version": item.dictionary_version,
            "status": item.status,
            "candidate_ids": [candidate.variant_id for candidate in item.candidates],
        }
        for item in dictionary.homographs
    ]
    candidates = [
        {
            "homograph_id": item.homograph_id,
            "variant_id": item.variant_id,
            "official_surface": item.official_surface,
            "official_stressed": item.official_stressed,
            "stress_position": item.stress_position,
            "status": item.status,
            "lifecycle_status": item.lifecycle_status,
            "provenance": list(item.provenance),
        }
        for item in dictionary.candidates
    ]
    analyses = [
        {
            **asdict(analysis),
            "homograph_id": candidate.homograph_id,
            "variant_id": candidate.variant_id,
            "analysis_id": analysis.provenance_id,
        }
        for candidate in dictionary.candidates
        for analysis in candidate.analyses
    ]
    payloads = {
        "homographs.jsonl": _json_lines(homographs),
        "candidates.jsonl": _json_lines(candidates),
        "analyses.jsonl": _json_lines(analyses),
        "build-report.json": _json_bytes(asdict(dictionary.report)),
    }
    if migration is not None:
        payloads["migration-report.json"] = _json_bytes(asdict(migration))
    if qa is not None:
        payloads["qa-report.json"] = _json_bytes(asdict(qa))
    for name, payload in payloads.items():
        _atomic_write(output_dir / name, payload)
    file_hashes = {
        name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(payloads.items())
    }
    manifest: Manifest = {
        "schema_version": "dictionary-v2",
        "release": dictionary.release,
        "logical_hash": dictionary.logical_hash,
        "files": file_hashes,
    }
    _atomic_write(output_dir / "manifest.json", _json_bytes(manifest))
    return manifest


def _json_lines(records: Sequence[Mapping[str, object]]) -> bytes:
    return b"".join(_json_bytes(record, newline=True) for record in records)


def _json_bytes(value: object, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + suffix
    ).encode()


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
