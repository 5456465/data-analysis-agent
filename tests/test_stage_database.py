"""Tests for build-time DuckDB artifact staging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.stage_database import ArtifactStagingError, stage_database


ARTIFACT_CONTENT = b"verified-duckdb-artifact"
ARTIFACT_URL = "https://example.invalid/data-v1/olist.duckdb"


def _write_manifest(
    path: Path,
    *,
    size_bytes: int | None = None,
    sha256: str | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "version": "data-v1",
                "url": ARTIFACT_URL,
                "size_bytes": (
                    len(ARTIFACT_CONTENT) if size_bytes is None else size_bytes
                ),
                "sha256": (
                    hashlib.sha256(ARTIFACT_CONTENT).hexdigest()
                    if sha256 is None
                    else sha256
                ),
            }
        ),
        encoding="utf-8",
    )
    return path


def _local_download(url: str, destination: Path) -> None:
    assert url == ARTIFACT_URL
    destination.write_bytes(ARTIFACT_CONTENT)


def test_valid_download_is_verified_and_atomically_published(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "manifest.json")
    target_path = tmp_path / "data" / "processed" / "olist.duckdb"

    downloaded = stage_database(
        manifest_path,
        target_path,
        downloader=_local_download,
    )

    assert downloaded is True
    assert target_path.read_bytes() == ARTIFACT_CONTENT
    assert not list(target_path.parent.glob("*.download"))


def test_sha256_mismatch_fails_without_publishing_target(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "manifest.json", sha256="0" * 64)
    target_path = tmp_path / "data" / "olist.duckdb"

    with pytest.raises(ArtifactStagingError, match="SHA256 mismatch"):
        stage_database(manifest_path, target_path, downloader=_local_download)

    assert not target_path.exists()
    assert not list(target_path.parent.glob("*.download"))


def test_size_mismatch_fails_without_publishing_target(tmp_path: Path) -> None:
    manifest_path = _write_manifest(
        tmp_path / "manifest.json",
        size_bytes=len(ARTIFACT_CONTENT) + 1,
    )
    target_path = tmp_path / "data" / "olist.duckdb"

    with pytest.raises(ArtifactStagingError, match="size mismatch"):
        stage_database(manifest_path, target_path, downloader=_local_download)

    assert not target_path.exists()
    assert not list(target_path.parent.glob("*.download"))


def test_matching_existing_target_skips_download(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "manifest.json")
    target_path = tmp_path / "data" / "olist.duckdb"
    target_path.parent.mkdir()
    target_path.write_bytes(ARTIFACT_CONTENT)

    def unexpected_download(url: str, destination: Path) -> None:
        raise AssertionError("matching target must not be downloaded again")

    downloaded = stage_database(
        manifest_path,
        target_path,
        downloader=unexpected_download,
    )

    assert downloaded is False
    assert target_path.read_bytes() == ARTIFACT_CONTENT


def test_download_failure_leaves_no_target_or_temporary_file(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path / "manifest.json")
    target_path = tmp_path / "data" / "olist.duckdb"

    def failed_download(url: str, destination: Path) -> None:
        raise OSError("network unavailable")

    with pytest.raises(ArtifactStagingError, match="download failed"):
        stage_database(manifest_path, target_path, downloader=failed_download)

    assert not target_path.exists()
    assert not list(target_path.parent.glob("*.download"))
