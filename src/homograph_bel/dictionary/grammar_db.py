"""Canonical GrammarDB homograph inventory and orthography mappings."""

import csv
import hashlib
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from homograph_bel.datasets.contracts import Orthography

ACUTE = "\N{COMBINING ACUTE ACCENT}"
BELARUSIAN_VOWELS = frozenset("аеёіоуыэюя")
OVERLAY_HEADERS = (
    "classical_surface",
    "classical_stressed",
    "official_surface",
    "official_stressed",
    "evidence",
    "reviewer_note",
    "status",
    "version",
)

type Identifier = Callable[[str, tuple[str, ...]], str]


@dataclass(frozen=True, slots=True)
class DictionaryVariant:
    """One allowed official stress variant."""

    homograph_id: str
    variant_id: str
    official_surface: str
    official_stressed: str
    dictionary_version: str


@dataclass(frozen=True, slots=True)
class ClassicalMapping:
    """A reviewed or proposed classical-to-official mapping."""

    classical_surface: str
    classical_stressed: str
    official_surface: str
    official_stressed: str
    evidence: str
    reviewer_note: str
    status: str
    version: str


@dataclass(frozen=True, slots=True)
class DictionaryBuildReport:
    """Counts produced while parsing a dictionary release."""

    total_lines: int
    invalid_lines: int
    duplicate_variants: int
    homographs: int
    variants: int


@dataclass(frozen=True, slots=True)
class DictionaryResolution:
    """Result of joining one source spelling and stress to the dictionary."""

    orthography: Orthography
    variant: DictionaryVariant | None
    reason: str | None
    mapping_version: str | None = None


class DictionaryIndex:
    """Lookup index for official variants and approved classical mappings."""

    def __init__(
        self,
        variants: tuple[DictionaryVariant, ...],
        report: DictionaryBuildReport,
        classical_mappings: Iterable[ClassicalMapping] = (),
    ) -> None:
        self.variants = variants
        self.report = report
        self._official: dict[tuple[str, str], DictionaryVariant] = {}
        self._official_surfaces: set[str] = set()
        for variant in variants:
            surface = normalize_unstressed(variant.official_surface)
            stressed = _normalize_stressed(variant.official_stressed)
            self._official[(surface, stressed)] = variant
            self._official_surfaces.add(surface)

        self._classical: dict[tuple[str, str], tuple[DictionaryVariant, str]] = {}
        self._known_classical_surfaces: set[str] = set()
        for mapping in classical_mappings:
            classical_surface = normalize_unstressed(mapping.classical_surface)
            self._known_classical_surfaces.add(classical_surface)
            if mapping.status != "approved":
                continue
            official_key = (
                normalize_unstressed(mapping.official_surface),
                _normalize_stressed(mapping.official_stressed),
            )
            variant = self._official.get(official_key)
            if variant is None:
                raise ValueError(
                    "approved classical mapping references an unknown official variant: "
                    f"{mapping.official_stressed}"
                )
            classical_key = (
                classical_surface,
                _normalize_stressed(mapping.classical_stressed),
            )
            self._classical[classical_key] = (variant, mapping.version)

    @classmethod
    def from_lines(
        cls,
        lines: Iterable[str],
        *,
        version: str,
        classical_mappings: Iterable[ClassicalMapping] = (),
        identifier: Identifier | None = None,
    ) -> "DictionaryIndex":
        """Build a homograph-only index from GrammarDB stressed lines."""

        make_identifier = identifier or _default_identifier
        grouped: dict[str, set[str]] = defaultdict(set)
        total_lines = 0
        invalid_lines = 0
        duplicate_variants = 0

        for raw_line in lines:
            total_lines += 1
            stressed = _normalize_stressed(raw_line.strip())
            if not stressed:
                continue
            if not _has_one_valid_stress(stressed):
                invalid_lines += 1
                continue
            surface = normalize_unstressed(stressed)
            if stressed in grouped[surface]:
                duplicate_variants += 1
            grouped[surface].add(stressed)

        variants: list[DictionaryVariant] = []
        identifiers: dict[str, tuple[str, ...]] = {}
        homograph_count = 0
        for surface in sorted(grouped):
            stressed_variants = grouped[surface]
            if len(stressed_variants) < 2:
                continue
            homograph_count += 1
            homograph_parts = ("official_2008", surface)
            homograph_id = make_identifier("h", homograph_parts)
            _check_identifier(identifiers, homograph_id, homograph_parts)
            for stressed in sorted(stressed_variants, reverse=True):
                variant_parts = (homograph_id, stressed)
                variant_id = make_identifier("v", variant_parts)
                _check_identifier(identifiers, variant_id, variant_parts)
                variants.append(
                    DictionaryVariant(
                        homograph_id=homograph_id,
                        variant_id=variant_id,
                        official_surface=surface,
                        official_stressed=stressed,
                        dictionary_version=version,
                    )
                )

        variants_tuple = tuple(variants)
        report = DictionaryBuildReport(
            total_lines=total_lines,
            invalid_lines=invalid_lines,
            duplicate_variants=duplicate_variants,
            homographs=homograph_count,
            variants=len(variants_tuple),
        )
        return cls(variants_tuple, report, classical_mappings)

    def resolve(self, surface: str, stressed: str) -> DictionaryResolution:
        """Resolve a source spelling and label without rewriting source text."""

        surface_key = normalize_unstressed(surface)
        stressed_key = _normalize_stressed(stressed)
        if surface_key in self._official_surfaces:
            variant = self._official.get((surface_key, stressed_key))
            reason = None if variant is not None else "dictionary_variant_not_allowed"
            return DictionaryResolution(Orthography.OFFICIAL_2008, variant, reason)

        classical = self._classical.get((surface_key, stressed_key))
        if classical is not None:
            variant, mapping_version = classical
            return DictionaryResolution(
                Orthography.CLASSICAL,
                variant,
                None,
                mapping_version,
            )
        if surface_key in self._known_classical_surfaces:
            return DictionaryResolution(
                Orthography.MIXED_OR_UNKNOWN,
                None,
                "classical_mapping_not_approved",
            )
        return DictionaryResolution(
            Orthography.MIXED_OR_UNKNOWN,
            None,
            "dictionary_target_missing",
        )


def normalize_unstressed(value: str) -> str:
    """Return NFC case-folded text with acute accents removed."""

    decomposed = unicodedata.normalize("NFD", value.strip()).replace(ACUTE, "")
    return unicodedata.normalize("NFC", decomposed).casefold()


def load_classical_overlay(path: Path) -> list[ClassicalMapping]:
    """Load a strict, versioned classical mapping CSV."""

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != OVERLAY_HEADERS:
            raise ValueError("unexpected classical overlay headers")
        return [
            ClassicalMapping(**{header: row[header] for header in OVERLAY_HEADERS})
            for row in reader
        ]


def _normalize_stressed(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip()).casefold()


def _has_one_valid_stress(value: str) -> bool:
    if value.count(ACUTE) != 1:
        return False
    acute_index = value.index(ACUTE)
    return acute_index > 0 and value[acute_index - 1].casefold() in BELARUSIAN_VOWELS


def _default_identifier(prefix: str, parts: tuple[str, ...]) -> str:
    payload = "\0".join(parts).encode()
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:20]}"


def _check_identifier(
    identifiers: dict[str, tuple[str, ...]],
    identifier: str,
    parts: tuple[str, ...],
) -> None:
    existing = identifiers.get(identifier)
    if existing is not None and existing != parts:
        raise ValueError(f"identifier collision for {identifier}")
    identifiers[identifier] = parts


# Dictionary v2 is re-exported here to preserve the existing GrammarDB import boundary.
from homograph_bel.dictionary.v2 import (  # noqa: E402
    DictionaryCandidate,
    DictionaryHomograph,
    DictionaryMigrationReport,
    DictionaryQAReport,
    DictionaryQASampleItem,
    DictionaryStatus,
    DictionaryV1Identity,
    DictionaryV2,
    DictionaryV2BuildReport,
    GrammarDBAnalysis,
    GrammarDBParseError,
    GrammarDBSourceContract,
    IdentityMigration,
    build_dictionary_v2,
    build_dictionary_v2_from_archive,
    load_grammar_db_source_contract,
    migrate_dictionary_v1_ids,
    select_dictionary_qa_sample,
    verify_grammar_db_archive,
)

__all__ = [
    "ClassicalMapping",
    "DictionaryCandidate",
    "DictionaryHomograph",
    "DictionaryMigrationReport",
    "DictionaryQAReport",
    "DictionaryQASampleItem",
    "DictionaryStatus",
    "DictionaryV1Identity",
    "DictionaryV2",
    "DictionaryV2BuildReport",
    "GrammarDBAnalysis",
    "GrammarDBParseError",
    "GrammarDBSourceContract",
    "IdentityMigration",
    "build_dictionary_v2",
    "build_dictionary_v2_from_archive",
    "load_classical_overlay",
    "load_grammar_db_source_contract",
    "migrate_dictionary_v1_ids",
    "normalize_unstressed",
    "select_dictionary_qa_sample",
    "verify_grammar_db_archive",
]
