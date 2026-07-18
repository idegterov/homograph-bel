"""Verified access to the bundled production Dictionary v2 resource."""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import tempfile
from importlib.resources import as_file, files
from pathlib import Path, PurePosixPath

from homograph_bel.dictionary import DictionaryIndex

BUNDLED_DICTIONARY_VERSION = "RELEASE-202601"
BUNDLED_DICTIONARY_ARCHIVE = f"dictionary-v2-{BUNDLED_DICTIONARY_VERSION}.tar.gz"
BUNDLED_DICTIONARY_SHA256 = "ed69710bf1bb9b57ec83eb17ca220485749a45e5e636c117ab543addd3f95390"

_REQUIRED_MEMBERS = frozenset(
    {
        "dictionary/manifest.json",
        "dictionary/homographs.jsonl",
        "dictionary/candidates.jsonl",
        "dictionary/analyses.jsonl",
    }
)


class DictionaryResourceError(ValueError):
    """Raised when the bundled dictionary cannot be verified or materialized."""


def bundled_dictionary_path(cache_root: Path | None = None) -> Path:
    """Return a verified materialized path to the bundled dictionary.

    The compressed package resource is checksum-verified and extracted once into
    a versioned user cache. Supplying ``cache_root`` is useful for controlled
    deployments and tests.
    """

    cache = cache_root if cache_root is not None else _default_cache_root()
    release_root = cache / f"dictionary-v2-{BUNDLED_DICTIONARY_VERSION}"
    dictionary = release_root / "dictionary"
    marker = release_root / ".archive-sha256"
    if _cache_is_current(dictionary, marker):
        return dictionary

    cache.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{release_root.name}-", dir=cache))
    try:
        resource = files(__package__).joinpath(BUNDLED_DICTIONARY_ARCHIVE)
        with as_file(resource) as archive:
            _extract_verified_archive(archive, staging, BUNDLED_DICTIONARY_SHA256)
        marker_path = staging / ".archive-sha256"
        marker_path.write_text(f"{BUNDLED_DICTIONARY_SHA256}\n", encoding="ascii")
        if release_root.exists():
            shutil.rmtree(release_root)
        os.replace(staging, release_root)
    except (DictionaryResourceError, OSError, tarfile.TarError) as error:
        raise DictionaryResourceError(f"cannot materialize bundled dictionary: {error}") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return dictionary


def bundled_dictionary_index(cache_root: Path | None = None) -> DictionaryIndex:
    """Load and validate the bundled dictionary into its immutable lookup index."""

    return DictionaryIndex.from_bundle(bundled_dictionary_path(cache_root))


def _extract_verified_archive(archive: Path, destination: Path, expected_sha256: str) -> None:
    """Verify and safely extract the exact Dictionary v2 archive members."""

    actual_sha256 = _file_sha256(archive)
    if actual_sha256 != expected_sha256:
        raise DictionaryResourceError(
            f"archive checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
        )

    try:
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            file_names: set[str] = set()
            for member in members:
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or not path.parts
                    or path.parts[0] != "dictionary"
                    or not (member.isfile() or member.isdir())
                ):
                    raise DictionaryResourceError(f"unsafe archive member: {member.name}")
                if member.isfile():
                    file_names.add(member.name)
            missing = _REQUIRED_MEMBERS - file_names
            if missing:
                raise DictionaryResourceError(
                    f"archive is missing required member: {sorted(missing)[0]}"
                )
            unexpected = file_names - _REQUIRED_MEMBERS
            if unexpected:
                raise DictionaryResourceError(
                    f"archive has unexpected member: {sorted(unexpected)[0]}"
                )
            destination.mkdir(parents=True, exist_ok=True)
            bundle.extractall(destination, members=members, filter="data")
    except (OSError, tarfile.TarError) as error:
        raise DictionaryResourceError(f"invalid dictionary archive: {error}") from error


def _default_cache_root() -> Path:
    configured = os.environ.get("HOMOGRAPH_BEL_CACHE")
    if configured:
        return Path(configured).expanduser()
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return base / "homograph-bel"


def _cache_is_current(dictionary: Path, marker: Path) -> bool:
    try:
        return marker.read_text(encoding="ascii").strip() == BUNDLED_DICTIONARY_SHA256 and all(
            (dictionary / PurePosixPath(name).name).is_file() for name in _REQUIRED_MEMBERS
        )
    except OSError:
        return False


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise DictionaryResourceError(f"cannot read dictionary archive: {error}") from error
    return digest.hexdigest()
