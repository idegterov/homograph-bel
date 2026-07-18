# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

import homograph_bel.resources as resources
from homograph_bel.resources import (
    BUNDLED_DICTIONARY_VERSION,
    DictionaryResourceError,
    _default_cache_root,
    _extract_verified_archive,
    _file_sha256,
    bundled_dictionary_index,
    bundled_dictionary_path,
)


def test_materializes_and_reuses_bundled_dictionary(tmp_path: Path) -> None:
    first = bundled_dictionary_path(tmp_path)
    second = bundled_dictionary_path(tmp_path)

    assert BUNDLED_DICTIONARY_VERSION == "RELEASE-202601"
    assert first == second
    assert first.name == "dictionary"
    assert (first / "manifest.json").is_file()
    assert (first.parent / ".archive-sha256").is_file()
    assert bundled_dictionary_index(tmp_path).release == BUNDLED_DICTIONARY_VERSION
    assert len(bundled_dictionary_index(tmp_path)) == 19_992


def test_replaces_an_incomplete_cached_dictionary(tmp_path: Path) -> None:
    dictionary = bundled_dictionary_path(tmp_path)
    (dictionary.parent / ".archive-sha256").write_text("stale", encoding="ascii")

    repaired = bundled_dictionary_path(tmp_path)

    assert repaired == dictionary
    assert (repaired / "manifest.json").is_file()
    assert (repaired.parent / ".archive-sha256").read_text(encoding="ascii").strip() != "stale"


def test_rejects_wrong_archive_hash(tmp_path: Path) -> None:
    archive = tmp_path / "dictionary.tar.gz"
    archive.write_bytes(b"not an archive")

    with pytest.raises(DictionaryResourceError, match="checksum"):
        _extract_verified_archive(archive, tmp_path / "output", "0" * 64)


def test_rejects_unsafe_or_incomplete_archives(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe.tar.gz"
    with tarfile.open(unsafe, "w:gz") as bundle:
        payload = b"bad"
        member = tarfile.TarInfo("../escape")
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))
    unsafe_hash = hashlib.sha256(unsafe.read_bytes()).hexdigest()

    with pytest.raises(DictionaryResourceError, match="unsafe"):
        _extract_verified_archive(unsafe, tmp_path / "unsafe-output", unsafe_hash)

    incomplete = tmp_path / "incomplete.tar.gz"
    with tarfile.open(incomplete, "w:gz") as bundle:
        payload = b"{}"
        member = tarfile.TarInfo("dictionary/manifest.json")
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))
    incomplete_hash = hashlib.sha256(incomplete.read_bytes()).hexdigest()

    with pytest.raises(DictionaryResourceError, match="missing"):
        _extract_verified_archive(incomplete, tmp_path / "incomplete-output", incomplete_hash)


def test_rejects_unexpected_members_and_invalid_tar(tmp_path: Path) -> None:
    archive = tmp_path / "unexpected.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name in (
            "dictionary/manifest.json",
            "dictionary/homographs.jsonl",
            "dictionary/candidates.jsonl",
            "dictionary/analyses.jsonl",
            "dictionary/extra.json",
        ):
            payload = b"{}"
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()

    with pytest.raises(DictionaryResourceError, match="unexpected"):
        _extract_verified_archive(archive, tmp_path / "unexpected-output", archive_hash)

    invalid = tmp_path / "invalid.tar.gz"
    invalid.write_bytes(b"not a tar archive")
    invalid_hash = hashlib.sha256(invalid.read_bytes()).hexdigest()
    with pytest.raises(DictionaryResourceError, match="invalid dictionary archive"):
        _extract_verified_archive(invalid, tmp_path / "invalid-output", invalid_hash)


def test_reports_materialization_and_archive_read_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_extract(_archive: Path, _destination: Path, _expected_sha256: str) -> None:
        raise DictionaryResourceError("simulated failure")

    monkeypatch.setattr(resources, "_extract_verified_archive", fail_extract)
    with pytest.raises(DictionaryResourceError, match="cannot materialize"):
        bundled_dictionary_path(tmp_path)
    assert not tuple(tmp_path.glob(".dictionary-v2-*"))

    with pytest.raises(DictionaryResourceError, match="cannot read"):
        _file_sha256(tmp_path / "missing.tar.gz")


def test_default_cache_root_honors_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured"
    monkeypatch.setenv("HOMOGRAPH_BEL_CACHE", str(configured))
    assert _default_cache_root() == configured

    monkeypatch.delenv("HOMOGRAPH_BEL_CACHE")
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg))
    assert _default_cache_root() == xdg / "homograph-bel"

    monkeypatch.delenv("XDG_CACHE_HOME")
    assert _default_cache_root().parts[-2:] == (".cache", "homograph-bel")
