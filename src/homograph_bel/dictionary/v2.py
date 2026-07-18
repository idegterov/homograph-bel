"""Linguistically enriched, deterministic GrammarDB Dictionary v2."""

from __future__ import annotations

import hashlib
import json
import tomllib
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast
from zipfile import BadZipFile, ZipFile

ACUTE = "\N{COMBINING ACUTE ACCENT}"
SPACING_ACUTE = "\N{ACUTE ACCENT}"
STRESS_MARKERS = frozenset(("+", ACUTE, SPACING_ACUTE))
BELARUSIAN_VOWELS = frozenset("аеёіоуыэюя")
OFFICIAL_2008 = "A2008"
UNSUPPORTED_FORM_TYPES = frozenset(("nonstandard", "potential", "short"))


class GrammarDBParseError(ValueError):
    """Raised when a GrammarDB XML source cannot satisfy the source contract."""


class DictionaryStatus(StrEnum):
    """Dictionary v2 linguistic and lifecycle statuses."""

    CONTEXTUAL = "contextual"
    FREE_VARIANT = "free_variant"
    CONFLICT = "conflict"
    CANDIDATE_ONLY = "candidate_only"
    PRODUCTION_SUPPORTED = "production_supported"


@dataclass(frozen=True, slots=True)
class GrammarDBSourceContract:
    """Pinned external GrammarDB release and expected XML members."""

    release: str
    asset_name: str
    url: str
    sha256: str
    orthography: str
    xml_members: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GrammarDBAnalysis:
    """One GrammarDB analysis supporting a pronunciation candidate."""

    release: str
    source_paradigm_id: str
    source_variant_id: str
    source_form_id: str
    lemma: str
    stressed_lemma: str
    pos: str
    paradigm_tag: str
    variant_tag: str
    form_tag: str
    meaning: str | None
    theme: str | None
    regulation: str | None
    variant_type: str | None
    form_type: str | None
    form_options: str | None
    source_dictionaries: tuple[str, ...]
    orthographies: tuple[str, ...]
    morphology: tuple[str, ...]
    phonetic_forms: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def paradigm_id(self) -> str:
        """Backward-compatible short name for the GrammarDB paradigm ID."""

        return self.source_paradigm_id

    @property
    def variant_id(self) -> str:
        """Backward-compatible short name for the GrammarDB-local variant ID."""

        return self.source_variant_id

    @property
    def form_id(self) -> str:
        """Backward-compatible short name for the source form ordinal."""

        return self.source_form_id

    @property
    def provenance_id(self) -> str:
        """Return the stable GrammarDB source coordinates for this analysis."""

        return (
            f"{self.release}:{self.source_paradigm_id}:"
            f"{self.source_variant_id}:{self.source_form_id}"
        )


@dataclass(frozen=True, slots=True)
class DictionaryCandidate:
    """One stressed spelling backed by one or more GrammarDB analyses."""

    homograph_id: str
    variant_id: str
    official_surface: str
    official_stressed: str
    stress_position: int
    status: DictionaryStatus
    lifecycle_status: DictionaryStatus
    analyses: tuple[GrammarDBAnalysis, ...]
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DictionaryHomograph:
    """One official lookup surface with two or more stressed candidates."""

    homograph_id: str
    official_surface: str
    dictionary_version: str
    status: DictionaryStatus
    candidates: tuple[DictionaryCandidate, ...]


@dataclass(frozen=True, slots=True)
class DictionaryV2BuildReport:
    """Auditable counts and exclusions from one deterministic XML build."""

    release: str
    total_paradigms: int
    total_variants: int
    total_forms: int
    invalid_paradigms: int
    invalid_forms: int
    excluded_records: int
    homographs: int
    candidates: int
    analyses: int
    exclusion_counts: tuple[tuple[str, int], ...]
    status_counts: tuple[tuple[str, int], ...]
    logical_hash: str


@dataclass(frozen=True, slots=True)
class DictionaryV2:
    """Immutable logical Dictionary v2 build."""

    release: str
    homographs: tuple[DictionaryHomograph, ...]
    report: DictionaryV2BuildReport
    logical_hash: str

    @property
    def candidates(self) -> tuple[DictionaryCandidate, ...]:
        """Return candidates in deterministic homograph and stress order."""

        return tuple(candidate for item in self.homographs for candidate in item.candidates)

    @property
    def analyses(self) -> tuple[GrammarDBAnalysis, ...]:
        """Return all source analyses in deterministic order."""

        return tuple(analysis for candidate in self.candidates for analysis in candidate.analyses)


@dataclass(frozen=True, slots=True)
class DictionaryV1Identity:
    """The identity-bearing subset of one Dictionary v1 candidate."""

    homograph_id: str
    variant_id: str
    official_surface: str
    official_stressed: str


@dataclass(frozen=True, slots=True)
class IdentityMigration:
    """One explicit Dictionary-v1-to-v2 identity relation."""

    old_homograph_id: str
    old_variant_id: str
    new_homograph_id: str | None
    new_variant_id: str | None
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class DictionaryMigrationReport:
    """Deterministic migration mappings and new Dictionary v2 identities."""

    mappings: tuple[IdentityMigration, ...]
    new_variant_ids: tuple[str, ...]
    logical_hash: str


@dataclass(frozen=True, slots=True)
class DictionaryQASampleItem:
    """One deterministic dictionary record selected for linguistic review."""

    homograph_id: str
    official_surface: str
    frequency: int
    frequency_band: str
    reason: str


@dataclass(frozen=True, slots=True)
class DictionaryQAReport:
    """High-frequency conflicts and a deterministic stratified tail sample."""

    high_frequency_conflicts: tuple[DictionaryQASampleItem, ...]
    tail_sample: tuple[DictionaryQASampleItem, ...]
    logical_hash: str


@dataclass(frozen=True, slots=True)
class _ParsedForm:
    surface: str
    stressed: str
    stress_position: int
    analysis: GrammarDBAnalysis


def build_dictionary_v2(
    source: str | bytes | Path | ET.Element,
    *,
    release: str,
    v1_identities: Iterable[DictionaryV1Identity] = (),
    status_overrides: Mapping[str, DictionaryStatus] | None = None,
) -> DictionaryV2:
    """Parse official-2008 GrammarDB XML and build a deterministic dictionary."""

    root = _parse_xml(source)
    if _local_name(root.tag) != "Wordlist":
        raise GrammarDBParseError("GrammarDB XML root must be Wordlist")

    totals = Counter[str]()
    exclusions = Counter[str]()
    grouped: dict[str, dict[str, list[GrammarDBAnalysis]]] = defaultdict(lambda: defaultdict(list))
    for paradigm in (item for item in root if _local_name(item.tag) == "Paradigm"):
        totals["paradigms"] += 1
        paradigm_id = paradigm.get("pdgId")
        paradigm_lemma = paradigm.get("lemma")
        if not paradigm_id or paradigm_lemma is None:
            totals["invalid_paradigms"] += 1
            exclusions["invalid_paradigm"] += 1
            continue
        for variant in (item for item in paradigm if _local_name(item.tag) == "Variant"):
            totals["variants"] += 1
            variant_lemma = variant.get("lemma")
            if variant_lemma is None:
                exclusions["invalid_variant"] += 1
                continue
            forms = [item for item in variant if _local_name(item.tag) == "Form"]
            for form_index, form in enumerate(forms):
                totals["forms"] += 1
                parsed, reason = _parse_form(
                    release,
                    paradigm,
                    paradigm_id,
                    variant,
                    variant_lemma,
                    form,
                    form_index,
                )
                if parsed is None:
                    if reason in {"missing_form", "invalid_stress"}:
                        totals["invalid_forms"] += 1
                    exclusions[reason] += 1
                    continue
                grouped[parsed.surface][parsed.stressed].append(parsed.analysis)

    return _assemble_dictionary(
        grouped,
        totals,
        exclusions,
        release=release,
        v1_identities=v1_identities,
        status_overrides=status_overrides,
    )


def _assemble_dictionary(
    grouped: Mapping[str, Mapping[str, list[GrammarDBAnalysis]]],
    totals: Counter[str],
    exclusions: Counter[str],
    *,
    release: str,
    v1_identities: Iterable[DictionaryV1Identity],
    status_overrides: Mapping[str, DictionaryStatus] | None,
) -> DictionaryV2:
    overrides = {
        _normalize_unstressed(surface): status
        for surface, status in (status_overrides or {}).items()
    }
    invalid_overrides = set(overrides.values()) - {
        DictionaryStatus.CONTEXTUAL,
        DictionaryStatus.FREE_VARIANT,
        DictionaryStatus.CONFLICT,
    }
    if invalid_overrides:
        raise ValueError("status overrides must use a linguistic status")
    identity_by_key, homograph_ids = _v1_identity_maps(v1_identities)
    homographs: list[DictionaryHomograph] = []
    used_overrides: set[str] = set()
    for surface, stressed_groups in sorted(grouped.items()):
        if len(stressed_groups) < 2:
            exclusions["not_a_homograph"] += sum(len(items) for items in stressed_groups.values())
            continue
        homograph_id = homograph_ids.get(surface) or _identifier("h", ("official_2008", surface))
        signature_groups = {
            _analysis_signature(analysis)
            for items in stressed_groups.values()
            for analysis in items
        }
        inferred_status = (
            DictionaryStatus.FREE_VARIANT
            if len(signature_groups) == 1
            else DictionaryStatus.CONTEXTUAL
        )
        status = overrides.get(surface, inferred_status)
        if surface in overrides:
            used_overrides.add(surface)
        candidates: list[DictionaryCandidate] = []
        for stressed, analyses in sorted(stressed_groups.items(), reverse=True):
            ordered = tuple(sorted(set(analyses), key=_analysis_sort_key))
            identity = identity_by_key.get((surface, stressed))
            variant_id = (
                identity.variant_id
                if identity is not None
                else _identifier("v", (homograph_id, stressed))
            )
            lifecycle = (
                DictionaryStatus.PRODUCTION_SUPPORTED
                if any(item.source_dictionaries for item in ordered)
                else DictionaryStatus.CANDIDATE_ONLY
            )
            candidates.append(
                DictionaryCandidate(
                    homograph_id=homograph_id,
                    variant_id=variant_id,
                    official_surface=surface,
                    official_stressed=stressed,
                    stress_position=_stress_position(stressed),
                    status=status,
                    lifecycle_status=lifecycle,
                    analyses=ordered,
                    provenance=tuple(item.provenance_id for item in ordered),
                )
            )
        homographs.append(
            DictionaryHomograph(
                homograph_id=homograph_id,
                official_surface=surface,
                dictionary_version=release,
                status=status,
                candidates=tuple(candidates),
            )
        )

    unknown_overrides = set(overrides) - used_overrides
    if unknown_overrides:
        raise ValueError(
            f"status overrides reference unknown surfaces: {sorted(unknown_overrides)}"
        )
    homographs_tuple = tuple(homographs)
    logical_hash = _logical_hash({"release": release, "homographs": homographs_tuple})
    all_candidates: tuple[DictionaryCandidate, ...] = tuple(
        item for homograph in homographs_tuple for item in homograph.candidates
    )
    analyses = tuple(item for candidate in all_candidates for item in candidate.analyses)
    status_counts = Counter(item.status.value for item in all_candidates)
    status_counts.update(item.lifecycle_status.value for item in all_candidates)
    report = DictionaryV2BuildReport(
        release=release,
        total_paradigms=totals["paradigms"],
        total_variants=totals["variants"],
        total_forms=totals["forms"],
        invalid_paradigms=totals["invalid_paradigms"],
        invalid_forms=totals["invalid_forms"],
        excluded_records=sum(exclusions.values()),
        homographs=len(homographs_tuple),
        candidates=len(all_candidates),
        analyses=len(analyses),
        exclusion_counts=tuple(sorted(exclusions.items())),
        status_counts=tuple(sorted(status_counts.items())),
        logical_hash=logical_hash,
    )
    return DictionaryV2(release, homographs_tuple, report, logical_hash)


def load_grammar_db_source_contract(path: Path) -> GrammarDBSourceContract:
    """Load the strict tracked GrammarDB archive contract."""

    with path.open("rb") as handle:
        data = tomllib.load(handle)
    required = ("release", "asset_name", "url", "sha256", "orthography", "xml_members")
    if set(data) != set(required) or not isinstance(data.get("xml_members"), list):
        raise ValueError("invalid GrammarDB source contract")
    return GrammarDBSourceContract(
        release=str(data["release"]),
        asset_name=str(data["asset_name"]),
        url=str(data["url"]),
        sha256=str(data["sha256"]),
        orthography=str(data["orthography"]),
        xml_members=tuple(str(item) for item in data["xml_members"]),
    )


def verify_grammar_db_archive(
    path: Path,
    contract: GrammarDBSourceContract,
) -> tuple[str, ...]:
    """Verify the pinned digest and exact XML member basenames."""

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != contract.sha256:
        raise ValueError(f"GrammarDB archive checksum mismatch: {digest}")
    try:
        with ZipFile(path) as archive:
            members = tuple(sorted(name for name in archive.namelist() if name.endswith(".xml")))
    except BadZipFile as error:
        raise ValueError("GrammarDB archive is not a valid ZIP file") from error
    basenames = tuple(Path(name).name for name in members)
    if tuple(sorted(basenames)) != tuple(sorted(contract.xml_members)):
        raise ValueError("GrammarDB archive XML members do not match the source contract")
    return members


def build_dictionary_v2_from_archive(
    path: Path,
    contract: GrammarDBSourceContract,
    *,
    v1_identities: Iterable[DictionaryV1Identity] = (),
    status_overrides: Mapping[str, DictionaryStatus] | None = None,
) -> DictionaryV2:
    """Build Dictionary v2 with a streaming two-pass scan of the release archive."""

    if contract.orthography != OFFICIAL_2008:
        raise ValueError("GrammarDB source contract must target A2008")
    members = verify_grammar_db_archive(path, contract)
    eligible_surfaces = _discover_homograph_surfaces(
        _archive_paradigms(path, members),
        contract.release,
    )
    grouped, totals, exclusions = _parse_paradigms(
        _archive_paradigms(path, members),
        contract.release,
        eligible_surfaces,
    )
    return _assemble_dictionary(
        grouped,
        totals,
        exclusions,
        release=contract.release,
        v1_identities=v1_identities,
        status_overrides=status_overrides,
    )


def _archive_paradigms(path: Path, members: tuple[str, ...]) -> Iterable[ET.Element]:
    with ZipFile(path) as archive:
        for member in members:
            with archive.open(member) as handle:
                root_seen = False
                for event, element in ET.iterparse(handle, events=("start", "end")):
                    if not root_seen and event == "start":
                        root_seen = True
                        if _local_name(element.tag) != "Wordlist":
                            raise GrammarDBParseError(
                                f"GrammarDB XML member is not a Wordlist: {member}"
                            )
                    if event == "end" and _local_name(element.tag) == "Paradigm":
                        yield element
                        element.clear()


def _discover_homograph_surfaces(
    paradigms: Iterable[ET.Element],
    release: str,
) -> set[str]:
    stressed_by_surface: dict[str, set[str]] = defaultdict(set)
    for paradigm in paradigms:
        paradigm_id = paradigm.get("pdgId")
        paradigm_lemma = paradigm.get("lemma")
        if not paradigm_id or paradigm_lemma is None:
            continue
        for variant in (item for item in paradigm if _local_name(item.tag) == "Variant"):
            variant_lemma = variant.get("lemma")
            if variant_lemma is None:
                continue
            forms = [item for item in variant if _local_name(item.tag) == "Form"]
            for form_index, form in enumerate(forms):
                parsed, _ = _parse_form(
                    release,
                    paradigm,
                    paradigm_id,
                    variant,
                    variant_lemma,
                    form,
                    form_index,
                )
                if parsed is not None:
                    stressed_by_surface[parsed.surface].add(parsed.stressed)
    return {surface for surface, stresses in stressed_by_surface.items() if len(stresses) >= 2}


def _parse_paradigms(
    paradigms: Iterable[ET.Element],
    release: str,
    eligible_surfaces: set[str],
) -> tuple[
    dict[str, dict[str, list[GrammarDBAnalysis]]],
    Counter[str],
    Counter[str],
]:
    totals = Counter[str]()
    exclusions = Counter[str]()
    grouped: dict[str, dict[str, list[GrammarDBAnalysis]]] = defaultdict(lambda: defaultdict(list))
    for paradigm in paradigms:
        totals["paradigms"] += 1
        paradigm_id = paradigm.get("pdgId")
        paradigm_lemma = paradigm.get("lemma")
        if not paradigm_id or paradigm_lemma is None:
            totals["invalid_paradigms"] += 1
            exclusions["invalid_paradigm"] += 1
            continue
        for variant in (item for item in paradigm if _local_name(item.tag) == "Variant"):
            totals["variants"] += 1
            variant_lemma = variant.get("lemma")
            if variant_lemma is None:
                exclusions["invalid_variant"] += 1
                continue
            forms = [item for item in variant if _local_name(item.tag) == "Form"]
            for form_index, form in enumerate(forms):
                totals["forms"] += 1
                parsed, reason = _parse_form(
                    release,
                    paradigm,
                    paradigm_id,
                    variant,
                    variant_lemma,
                    form,
                    form_index,
                )
                if parsed is None:
                    if reason in {"missing_form", "invalid_stress"}:
                        totals["invalid_forms"] += 1
                    exclusions[reason] += 1
                elif parsed.surface in eligible_surfaces:
                    grouped[parsed.surface][parsed.stressed].append(parsed.analysis)
                else:
                    exclusions["not_a_homograph"] += 1
    return grouped, totals, exclusions


def migrate_dictionary_v1_ids(
    identities: Iterable[DictionaryV1Identity],
    dictionary: DictionaryV2,
) -> DictionaryMigrationReport:
    """Map exact v1 pronunciation identities and explicitly deprecate the rest."""

    new_by_key = {
        (candidate.official_surface, candidate.official_stressed): candidate
        for candidate in dictionary.candidates
    }
    mappings: list[IdentityMigration] = []
    used_new: set[str] = set()
    for old in sorted(identities, key=lambda item: (item.homograph_id, item.variant_id)):
        key = (
            _normalize_unstressed(old.official_surface),
            _normalize_stressed(old.official_stressed),
        )
        candidate = new_by_key.get(key)
        if candidate is None:
            mappings.append(
                IdentityMigration(
                    old.homograph_id,
                    old.variant_id,
                    None,
                    None,
                    "deprecated",
                    "pronunciation_not_in_dictionary_v2",
                )
            )
            continue
        used_new.add(candidate.variant_id)
        mappings.append(
            IdentityMigration(
                old.homograph_id,
                old.variant_id,
                candidate.homograph_id,
                candidate.variant_id,
                "preserved",
                "same_surface_and_stressed_spelling",
            )
        )
    new_ids = tuple(
        sorted(
            candidate.variant_id
            for candidate in dictionary.candidates
            if candidate.variant_id not in used_new
        )
    )
    mappings_tuple = tuple(mappings)
    logical_hash = _logical_hash({"mappings": mappings_tuple, "new_variant_ids": new_ids})
    return DictionaryMigrationReport(mappings_tuple, new_ids, logical_hash)


def select_dictionary_qa_sample(
    dictionary: DictionaryV2,
    *,
    frequencies: Mapping[str, int],
    tail_size: int,
    seed: str,
) -> DictionaryQAReport:
    """Select every conflict plus a stable round-robin frequency-band sample."""

    items = {
        homograph.official_surface: DictionaryQASampleItem(
            homograph_id=homograph.homograph_id,
            official_surface=homograph.official_surface,
            frequency=frequencies.get(homograph.official_surface, 0),
            frequency_band=_frequency_band(frequencies.get(homograph.official_surface, 0)),
            reason="conflict" if homograph.status is DictionaryStatus.CONFLICT else "tail_sample",
        )
        for homograph in dictionary.homographs
    }
    conflicts = tuple(
        sorted(
            (
                items[item.official_surface]
                for item in dictionary.homographs
                if item.status is DictionaryStatus.CONFLICT
            ),
            key=lambda item: (-item.frequency, item.official_surface),
        )
    )
    conflict_surfaces = {item.official_surface for item in conflicts}
    by_band: dict[str, list[DictionaryQASampleItem]] = {"high": [], "medium": [], "low": []}
    for item in items.values():
        if item.official_surface not in conflict_surfaces:
            by_band[item.frequency_band].append(item)
    for band_items in by_band.values():
        band_items.sort(key=lambda item: _sample_score(seed, item.official_surface))
    tail: list[DictionaryQASampleItem] = []
    while len(tail) < tail_size and any(by_band.values()):
        for band in ("high", "medium", "low"):
            if by_band[band] and len(tail) < tail_size:
                tail.append(by_band[band].pop(0))
    conflicts_tuple = tuple(conflicts)
    tail_tuple = tuple(tail)
    logical_hash = _logical_hash({"conflicts": conflicts_tuple, "tail": tail_tuple, "seed": seed})
    return DictionaryQAReport(conflicts_tuple, tail_tuple, logical_hash)


def _frequency_band(frequency: int) -> str:
    if frequency >= 1000:
        return "high"
    if frequency >= 100:
        return "medium"
    return "low"


def _sample_score(seed: str, surface: str) -> str:
    return hashlib.sha256(f"{seed}\0{surface}".encode()).hexdigest()


def _parse_form(
    release: str,
    paradigm: ET.Element,
    paradigm_id: str,
    variant: ET.Element,
    variant_lemma: str,
    form: ET.Element,
    form_index: int,
) -> tuple[_ParsedForm | None, str]:
    text = (form.text or "").strip()
    if not text or form.get("tag") is None:
        return None, "missing_form"
    form_type = form.get("type")
    if form_type in UNSUPPORTED_FORM_TYPES:
        return None, "unsupported_form_type"
    spelling_flags = form.get("pravapis")
    if spelling_flags is None:
        spelling_flags = variant.get("pravapis")
    orthographies = _tokens(spelling_flags)
    if OFFICIAL_2008 not in orthographies:
        return None, "not_official_2008"
    try:
        stressed = _normalize_stressed(text)
        stress_position = _stress_position(stressed)
    except ValueError:
        return None, "invalid_stress"
    surface = _normalize_unstressed(stressed)
    nested_sources = tuple(
        item.get("name") or ""
        for item in variant
        if _local_name(item.tag) == "Slounik" and item.get("name")
    )
    source_flags = form.get("slouniki")
    if source_flags is None:
        source_flags = variant.get("slouniki")
    sources = tuple(sorted(set(_tokens(source_flags) + nested_sources)))
    morphology = tuple(
        (item.text or "").strip()
        for item in variant
        if _local_name(item.tag) == "Morph" and (item.text or "").strip()
    )
    phonetic_forms = tuple(
        (item.text or "").strip()
        for item in variant
        if _local_name(item.tag) == "Fan" and (item.text or "").strip()
    )
    notes = tuple(
        (item.text or "").strip()
        for item in (*paradigm, *variant, *form)
        if _local_name(item.tag) == "Note" and (item.text or "").strip()
    )
    paradigm_tag = paradigm.get("tag") or ""
    analysis = GrammarDBAnalysis(
        release=release,
        source_paradigm_id=paradigm_id,
        source_variant_id=variant.get("id") or "",
        source_form_id=str(form_index),
        lemma=_normalize_unstressed(variant_lemma),
        stressed_lemma=_normalize_optional_stressed(variant_lemma),
        pos=paradigm_tag[:1],
        paradigm_tag=paradigm_tag,
        variant_tag=variant.get("tag") or "",
        form_tag=form.get("tag") or "",
        meaning=paradigm.get("meaning"),
        theme=paradigm.get("theme"),
        regulation=variant.get("regulation") or paradigm.get("regulation"),
        variant_type=variant.get("type"),
        form_type=form_type,
        form_options=form.get("options"),
        source_dictionaries=sources,
        orthographies=orthographies,
        morphology=morphology,
        phonetic_forms=phonetic_forms,
        notes=notes,
    )
    return _ParsedForm(surface, stressed, stress_position, analysis), ""


def _parse_xml(source: str | bytes | Path | ET.Element) -> ET.Element:
    try:
        if isinstance(source, ET.Element):
            return source
        if isinstance(source, Path):
            return ET.parse(source).getroot()
        return ET.fromstring(source)
    except (ET.ParseError, OSError) as error:
        raise GrammarDBParseError(f"invalid GrammarDB XML: {error}") from error


def _normalize_stressed(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.strip()).casefold()
    output: list[str] = []
    stresses = 0
    for character in normalized:
        if character in STRESS_MARKERS:
            if not output or output[-1] not in BELARUSIAN_VOWELS:
                raise ValueError("stress must follow a Belarusian vowel")
            output.append(ACUTE)
            stresses += 1
        else:
            output.append(character)
    if stresses != 1:
        raise ValueError("exactly one stress is required")
    return unicodedata.normalize("NFC", "".join(output))


def _normalize_optional_stressed(value: str) -> str:
    try:
        return _normalize_stressed(value)
    except ValueError:
        return unicodedata.normalize("NFC", value.strip()).casefold()


def _normalize_unstressed(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.strip()).casefold()
    return unicodedata.normalize(
        "NFC", "".join(character for character in decomposed if character not in STRESS_MARKERS)
    )


def _stress_position(value: str) -> int:
    decomposed = unicodedata.normalize("NFD", value)
    accent_index = decomposed.index(ACUTE)
    return sum(character in BELARUSIAN_VOWELS for character in decomposed[:accent_index]) - 1


def _tokens(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(sorted(item.strip() for item in value.split(",") if item.strip()))


def _analysis_signature(analysis: GrammarDBAnalysis) -> tuple[str, str, str | None]:
    return (analysis.lemma, analysis.pos, analysis.meaning)


def _analysis_sort_key(analysis: GrammarDBAnalysis) -> tuple[str, str, str, str]:
    return (
        analysis.source_paradigm_id,
        analysis.source_variant_id,
        analysis.source_form_id,
        analysis.form_tag,
    )


def _v1_identity_maps(
    identities: Iterable[DictionaryV1Identity],
) -> tuple[
    dict[tuple[str, str], DictionaryV1Identity],
    dict[str, str],
]:
    by_key: dict[tuple[str, str], DictionaryV1Identity] = {}
    homograph_ids: dict[str, str] = {}
    ids: dict[str, tuple[str, str]] = {}
    for identity in identities:
        surface = _normalize_unstressed(identity.official_surface)
        stressed = _normalize_stressed(identity.official_stressed)
        key = (surface, stressed)
        if identity.variant_id in ids and ids[identity.variant_id] != key:
            raise ValueError(f"Dictionary v1 variant ID is reused: {identity.variant_id}")
        if surface in homograph_ids and homograph_ids[surface] != identity.homograph_id:
            raise ValueError(f"Dictionary v1 homograph IDs disagree for {surface}")
        ids[identity.variant_id] = key
        homograph_ids[surface] = identity.homograph_id
        by_key[key] = identity
    return by_key, homograph_ids


def _identifier(prefix: str, parts: tuple[str, ...]) -> str:
    payload = "\0".join(parts).encode()
    return f"{prefix}_{hashlib.sha256(payload).hexdigest()[:20]}"


def _logical_hash(value: object) -> str:
    payload = json.dumps(
        _json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _json_value(value: object) -> object:
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _json_value(item) for key, item in mapping.items()}
    if isinstance(value, tuple | list):
        items = cast(Iterable[object], value)
        return [_json_value(item) for item in items]
    return value


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
