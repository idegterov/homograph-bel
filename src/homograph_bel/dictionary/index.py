"""Validated, immutable lookup index for a Dictionary v2 output bundle."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from types import MappingProxyType
from typing import cast

from homograph_bel.dictionary.v2 import (
    STRESS_MARKERS,
    DictionaryCandidate,
    DictionaryHomograph,
    DictionaryStatus,
    GrammarDBAnalysis,
)

REQUIRED_TABLES = ("homographs.jsonl", "candidates.jsonl", "analyses.jsonl")
APOSTROPHE_TRANSLATION = str.maketrans({"\u2019": "'", "\u02bc": "'"})
LINGUISTIC_STATUSES = frozenset(
    (DictionaryStatus.CONTEXTUAL, DictionaryStatus.FREE_VARIANT, DictionaryStatus.CONFLICT)
)
LIFECYCLE_STATUSES = frozenset(
    (DictionaryStatus.CANDIDATE_ONLY, DictionaryStatus.PRODUCTION_SUPPORTED)
)


class DictionaryBundleError(ValueError):
    """Raised when a Dictionary v2 bundle cannot satisfy its contract."""


def normalize_lookup(value: str) -> str:
    """Normalize stress, case, NFC, and documented apostrophe variants for lookup."""

    decomposed = unicodedata.normalize("NFD", value.strip()).casefold()
    unstressed = "".join(character for character in decomposed if character not in STRESS_MARKERS)
    return unicodedata.normalize("NFC", unstressed).translate(APOSTROPHE_TRANSLATION)


class DictionaryIndex:
    """Preloaded Dictionary v2 records with constant-time normalized lookup."""

    __slots__ = ("_by_surface", "_homographs", "release")

    def __init__(self, release: str, homographs: tuple[DictionaryHomograph, ...]) -> None:
        """Create an index from already validated and joined homographs."""

        self.release = release
        self._homographs = tuple(
            sorted(homographs, key=lambda item: normalize_lookup(item.official_surface))
        )
        self._by_surface: Mapping[str, DictionaryHomograph] = MappingProxyType(
            {normalize_lookup(item.official_surface): item for item in self._homographs}
        )

    @classmethod
    def from_bundle(cls, bundle: Path) -> DictionaryIndex:
        """Load and validate the linked tables and hashes in a Dictionary v2 bundle."""

        manifest = _load_manifest(bundle)
        release = _required_string(manifest, "release", "manifest.json")
        expected_logical_hash = _required_string(manifest, "logical_hash", "manifest.json")
        files = _required_mapping(manifest, "files", "manifest.json")
        _verify_files(bundle, files)
        homograph_rows = _load_jsonl(bundle / "homographs.jsonl")
        candidate_rows = _load_jsonl(bundle / "candidates.jsonl")
        analysis_rows = _load_jsonl(bundle / "analyses.jsonl")
        homographs = _join_records(homograph_rows, candidate_rows, analysis_rows, release)
        if _dictionary_logical_hash(release, homographs) != expected_logical_hash:
            raise DictionaryBundleError("dictionary logical hash mismatch")
        return cls(release, homographs)

    def __len__(self) -> int:
        """Return the number of indexed homograph surfaces."""

        return len(self._homographs)

    def get_homograph(self, surface: str) -> DictionaryHomograph | None:
        """Return one canonical homograph by normalized surface, if present."""

        return self._by_surface.get(normalize_lookup(surface))

    def list_homographs(
        self,
        *,
        status: DictionaryStatus | None = None,
        limit: int | None = None,
    ) -> tuple[DictionaryHomograph, ...]:
        """List canonical homographs in deterministic surface order."""

        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        selected = (
            self._homographs
            if status is None
            else tuple(item for item in self._homographs if item.status is status)
        )
        return selected if limit is None else selected[:limit]


def _load_manifest(bundle: Path) -> dict[str, object]:
    path = bundle / "manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected dictionary-v2 object")
        manifest = cast(dict[str, object], value)
        if manifest.get("schema_version") != "dictionary-v2":
            raise ValueError("expected dictionary-v2 object")
        return manifest
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise DictionaryBundleError(f"invalid manifest.json: {error}") from error


def _verify_files(bundle: Path, files: Mapping[str, object]) -> None:
    bundle_root = bundle.resolve()
    for name in sorted(set(REQUIRED_TABLES) | set(files)):
        expected = files.get(name)
        path = bundle / name
        relative = Path(name)
        if relative.is_absolute() or relative.name != name or path.resolve().parent != bundle_root:
            raise DictionaryBundleError(f"unsafe manifest filename: {name}")
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise DictionaryBundleError(f"cannot read {name}: {error}") from error
        if not isinstance(expected, str) or actual != expected:
            raise DictionaryBundleError(f"hash mismatch for {name}")


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("record must be a JSON object")
                records.append(cast(dict[str, object], value))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        line_number = len(records) + 1
        raise DictionaryBundleError(
            f"{path.name}:{line_number}: invalid JSON record: {error}"
        ) from error
    return records


def _join_records(
    homograph_rows: list[dict[str, object]],
    candidate_rows: list[dict[str, object]],
    analysis_rows: list[dict[str, object]],
    release: str,
) -> tuple[DictionaryHomograph, ...]:
    analyses_by_variant: dict[str, list[GrammarDBAnalysis]] = defaultdict(list)
    analysis_homographs: dict[str, set[str]] = defaultdict(set)
    analysis_ids: set[str] = set()
    for row in analysis_rows:
        analysis_id = _required_string(row, "analysis_id", "analysis")
        if analysis_id in analysis_ids:
            raise DictionaryBundleError(f"duplicate analysis_id: {analysis_id}")
        analysis_ids.add(analysis_id)
        variant_id = _required_string(row, "variant_id", "analysis")
        homograph_id = _required_string(row, "homograph_id", "analysis")
        analysis = _analysis(row)
        if analysis.provenance_id != analysis_id:
            raise DictionaryBundleError(
                f"analysis_id differs from source coordinates: {analysis_id}"
            )
        if analysis.release != release:
            raise DictionaryBundleError(f"analysis release differs from manifest: {analysis_id}")
        analyses_by_variant[variant_id].append(analysis)
        analysis_homographs[variant_id].add(homograph_id)

    candidates: dict[str, DictionaryCandidate] = {}
    for row in candidate_rows:
        variant_id = _required_string(row, "variant_id", "candidate")
        if variant_id in candidates:
            raise DictionaryBundleError(f"duplicate variant_id: {variant_id}")
        candidates[variant_id] = _candidate(row, analyses_by_variant.get(variant_id, []))

    unknown_analysis_variants = set(analyses_by_variant) - set(candidates)
    if unknown_analysis_variants:
        raise DictionaryBundleError(
            f"analysis references unknown variant_id: {sorted(unknown_analysis_variants)[0]}"
        )
    for variant_id, candidate in candidates.items():
        if not candidate.analyses:
            raise DictionaryBundleError(f"candidate {variant_id} must have at least one analysis")
        if analysis_homographs[variant_id] != {candidate.homograph_id}:
            raise DictionaryBundleError(
                f"analysis homograph_id differs for candidate: {variant_id}"
            )
        expected_provenance = tuple(item.provenance_id for item in candidate.analyses)
        if candidate.provenance != expected_provenance:
            raise DictionaryBundleError(f"candidate provenance differs from analyses: {variant_id}")

    homograph_ids = [_required_string(row, "homograph_id", "homograph") for row in homograph_rows]
    if len(homograph_ids) != len(set(homograph_ids)):
        raise DictionaryBundleError("duplicate homograph_id")
    known_homographs = set(homograph_ids)
    if any(candidate.homograph_id not in known_homographs for candidate in candidates.values()):
        raise DictionaryBundleError("candidate has dangling homograph_id")

    homographs = tuple(_homograph(row, candidates, release) for row in homograph_rows)
    linked_candidates = {
        candidate.variant_id for homograph in homographs for candidate in homograph.candidates
    }
    unlinked_candidates = set(candidates) - linked_candidates
    if unlinked_candidates:
        raise DictionaryBundleError(
            f"candidate rows not linked by homographs: {sorted(unlinked_candidates)[0]}"
        )
    surfaces = [normalize_lookup(item.official_surface) for item in homographs]
    if len(surfaces) != len(set(surfaces)):
        raise DictionaryBundleError("duplicate normalized homograph surface")
    return homographs


def _analysis(row: Mapping[str, object]) -> GrammarDBAnalysis:
    return GrammarDBAnalysis(
        release=_required_string(row, "release", "analysis"),
        source_paradigm_id=_required_string(row, "source_paradigm_id", "analysis"),
        source_variant_id=_string(row, "source_variant_id", "analysis"),
        source_form_id=_required_string(row, "source_form_id", "analysis"),
        lemma=_string(row, "lemma", "analysis"),
        stressed_lemma=_string(row, "stressed_lemma", "analysis"),
        pos=_string(row, "pos", "analysis"),
        paradigm_tag=_string(row, "paradigm_tag", "analysis"),
        variant_tag=_string(row, "variant_tag", "analysis"),
        form_tag=_string(row, "form_tag", "analysis"),
        meaning=_optional_string(row, "meaning", "analysis"),
        theme=_optional_string(row, "theme", "analysis"),
        regulation=_optional_string(row, "regulation", "analysis"),
        variant_type=_optional_string(row, "variant_type", "analysis"),
        form_type=_optional_string(row, "form_type", "analysis"),
        form_options=_optional_string(row, "form_options", "analysis"),
        source_dictionaries=_string_tuple(row, "source_dictionaries", "analysis"),
        orthographies=_string_tuple(row, "orthographies", "analysis"),
        morphology=_string_tuple(row, "morphology", "analysis"),
        phonetic_forms=_string_tuple(row, "phonetic_forms", "analysis"),
        notes=_string_tuple(row, "notes", "analysis"),
    )


def _candidate(row: Mapping[str, object], analyses: list[GrammarDBAnalysis]) -> DictionaryCandidate:
    try:
        stress_position = row["stress_position"]
        if not isinstance(stress_position, int) or isinstance(stress_position, bool):
            raise TypeError("stress_position must be an integer")
        status = DictionaryStatus(_required_string(row, "status", "candidate"))
        lifecycle = DictionaryStatus(_required_string(row, "lifecycle_status", "candidate"))
        if status not in LINGUISTIC_STATUSES:
            raise ValueError("candidate linguistic status is outside its allowed domain")
        if lifecycle not in LIFECYCLE_STATUSES:
            raise ValueError("candidate lifecycle status is outside its allowed domain")
        return DictionaryCandidate(
            homograph_id=_required_string(row, "homograph_id", "candidate"),
            variant_id=_required_string(row, "variant_id", "candidate"),
            official_surface=_required_string(row, "official_surface", "candidate"),
            official_stressed=_required_string(row, "official_stressed", "candidate"),
            stress_position=stress_position,
            status=status,
            lifecycle_status=lifecycle,
            analyses=tuple(analyses),
            provenance=_string_tuple(row, "provenance", "candidate"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise DictionaryBundleError(f"invalid candidate record: {error}") from error


def _homograph(
    row: Mapping[str, object], candidates: Mapping[str, DictionaryCandidate], release: str
) -> DictionaryHomograph:
    homograph_id = _required_string(row, "homograph_id", "homograph")
    surface = _required_string(row, "official_surface", "homograph")
    candidate_ids = _string_tuple(row, "candidate_ids", "homograph")
    if len(candidate_ids) != len(set(candidate_ids)):
        raise DictionaryBundleError(f"homograph candidate_ids must be unique: {homograph_id}")
    try:
        linked = tuple(candidates[item] for item in candidate_ids)
        status = DictionaryStatus(_required_string(row, "status", "homograph"))
        if status not in LINGUISTIC_STATUSES:
            raise ValueError("homograph linguistic status is outside its allowed domain")
    except (KeyError, ValueError) as error:
        raise DictionaryBundleError(f"invalid homograph {homograph_id}: {error}") from error
    if len(linked) < 2:
        raise DictionaryBundleError(f"homograph {homograph_id} must have at least two candidates")
    if any(item.homograph_id != homograph_id for item in linked):
        raise DictionaryBundleError(f"candidate belongs to another homograph: {homograph_id}")
    if any(normalize_lookup(item.official_surface) != normalize_lookup(surface) for item in linked):
        raise DictionaryBundleError(f"candidate surface differs from homograph: {homograph_id}")
    if any(item.status is not status for item in linked):
        raise DictionaryBundleError(f"candidate status differs from homograph: {homograph_id}")
    dictionary_version = _required_string(row, "dictionary_version", "homograph")
    if dictionary_version != release:
        raise DictionaryBundleError(f"dictionary version differs from manifest: {homograph_id}")
    return DictionaryHomograph(homograph_id, surface, dictionary_version, status, linked)


def _required_mapping(row: Mapping[str, object], key: str, context: str) -> Mapping[str, object]:
    value = row.get(key)
    if not isinstance(value, dict):
        raise DictionaryBundleError(f"{context} field {key} must be an object")
    return cast(dict[str, object], value)


def _required_string(row: Mapping[str, object], key: str, context: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise DictionaryBundleError(f"{context} field {key} must be a non-empty string")
    return value


def _string(row: Mapping[str, object], key: str, context: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise DictionaryBundleError(f"{context} field {key} must be a string")
    return value


def _optional_string(row: Mapping[str, object], key: str, context: str) -> str | None:
    value = row.get(key)
    if value is not None and not isinstance(value, str):
        raise DictionaryBundleError(f"{context} field {key} must be a string or null")
    return value


def _string_tuple(row: Mapping[str, object], key: str, context: str) -> tuple[str, ...]:
    value = row.get(key)
    if not isinstance(value, list):
        raise DictionaryBundleError(f"{context} field {key} must be a list of strings")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise DictionaryBundleError(f"{context} field {key} must be a list of strings")
    return tuple(cast(list[str], items))


def _dictionary_logical_hash(release: str, homographs: tuple[DictionaryHomograph, ...]) -> str:
    payload = json.dumps(
        {"release": release, "homographs": [asdict(item) for item in homographs]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = ["DictionaryBundleError", "DictionaryIndex", "normalize_lookup"]
