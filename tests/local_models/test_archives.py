"""Archive extraction refuses hostile members (M16.5e).

A digest-verified archive is still untrusted input: the digest proves the
bytes are the ones the manifest pinned, not that whoever built them was
careful. Every case here builds a malicious archive by hand and asserts
nothing lands outside the extraction directory.
"""

from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from syzygy.local_models.archives import (
    ArchiveError,
    extract_archive,
    find_executable,
    make_executable,
)
from syzygy.local_models.contracts import FailureKind


def detail_of(caught) -> str:
    """`ArchiveError`'s message is the user-facing sentence; the specific
    reason - which member, and why - lives in `detail`."""
    return caught.value.failure.detail or ""


def write_tar(path: Path, members: list[tuple[str, bytes]]) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            bundle.addfile(info, io.BytesIO(payload))


def write_tar_link(path: Path, name: str, target: str, *, symlink: bool = True) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        info = tarfile.TarInfo(name)
        info.type = tarfile.SYMTYPE if symlink else tarfile.LNKTYPE
        info.linkname = target
        bundle.addfile(info)


def test_a_normal_archive_extracts(tmp_path: Path) -> None:
    archive = tmp_path / "good.tar.gz"
    write_tar(archive, [("llama-b1/llama-server", b"#!/bin/sh\n"), ("llama-b1/LICENSE", b"MIT")])

    destination = extract_archive(archive, tmp_path / "out", archive_format="tar.gz")

    assert (destination / "llama-b1" / "llama-server").read_bytes() == b"#!/bin/sh\n"


def test_a_traversal_member_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    write_tar(archive, [("../escaped", b"x")])

    with pytest.raises(ArchiveError) as caught:
        extract_archive(archive, tmp_path / "out", archive_format="tar.gz")

    assert caught.value.failure.kind is FailureKind.ARCHIVE_UNSAFE
    assert not (tmp_path / "escaped").exists()


def test_an_absolute_member_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    write_tar(archive, [("/etc/syzygy-owned", b"x")])

    with pytest.raises(ArchiveError) as caught:
        extract_archive(archive, tmp_path / "out", archive_format="tar.gz")
    assert "absolute" in detail_of(caught)


def test_a_symlink_pointing_outside_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    write_tar_link(archive, "llama-b1/escape", "../../../../etc/passwd")

    with pytest.raises(ArchiveError) as caught:
        extract_archive(archive, tmp_path / "out", archive_format="tar.gz")
    assert "points outside" in detail_of(caught)


def test_a_hard_link_pointing_outside_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    write_tar_link(archive, "llama-b1/escape", "../../../etc/hosts", symlink=False)

    with pytest.raises(ArchiveError) as caught:
        extract_archive(archive, tmp_path / "out", archive_format="tar.gz")
    assert "points outside" in detail_of(caught)


def test_a_device_node_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        info = tarfile.TarInfo("dev/null")
        info.type = tarfile.CHRTYPE
        bundle.addfile(info)

    with pytest.raises(ArchiveError) as caught:
        extract_archive(archive, tmp_path / "out", archive_format="tar.gz")
    assert "device node" in detail_of(caught)


def test_a_compression_bomb_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("syzygy.local_models.archives.MAX_EXTRACTED_BYTES", 1024)
    archive = tmp_path / "bomb.tar.gz"
    write_tar(archive, [("big", b"\0" * 4096)])

    with pytest.raises(ArchiveError) as caught:
        extract_archive(archive, tmp_path / "out", archive_format="tar.gz")
    assert "more than Syzygy will accept" in detail_of(caught)


def test_a_zip_extracts_flat_like_the_windows_release(tmp_path: Path) -> None:
    archive = tmp_path / "win.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("llama-server.exe", b"MZ")
        bundle.writestr("ggml-base.dll", b"MZ")

    destination = extract_archive(archive, tmp_path / "out", archive_format="zip")

    assert (destination / "llama-server.exe").read_bytes() == b"MZ"


def test_a_zip_with_a_traversal_member_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escaped.exe", b"MZ")

    with pytest.raises(ArchiveError):
        extract_archive(archive, tmp_path / "out", archive_format="zip")

    assert not (tmp_path / "escaped.exe").exists()


def test_an_unsupported_format_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ArchiveError) as caught:
        extract_archive(tmp_path / "x", tmp_path / "out", archive_format="7z")
    assert "unsupported archive format" in detail_of(caught)


def test_an_unreadable_archive_is_a_typed_failure(tmp_path: Path) -> None:
    archive = tmp_path / "broken.tar.gz"
    archive.write_bytes(b"not a tarball at all")

    with pytest.raises(ArchiveError) as caught:
        extract_archive(archive, tmp_path / "out", archive_format="tar.gz")
    assert "could not be read" in detail_of(caught)


def test_find_executable_searches_both_archive_layouts(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "llama-b1"
    nested.mkdir(parents=True)
    (nested / "llama-server").write_text("x")
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "llama-server.exe").write_text("x")

    assert find_executable(tmp_path / "nested", ("llama-server", "llama-server.exe")) == (
        nested / "llama-server"
    )
    assert find_executable(flat, ("llama-server", "llama-server.exe")) == (
        flat / "llama-server.exe"
    )
    assert find_executable(tmp_path / "nested", ("nothing-here",)) is None


def test_make_executable_is_safe_on_a_missing_file(tmp_path: Path) -> None:
    make_executable(tmp_path / "absent")
