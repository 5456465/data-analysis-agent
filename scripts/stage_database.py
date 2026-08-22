"""Stage the versioned DuckDB artifact before a Docker image is built."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_MANIFEST_PATH = Path("deployment/olist_duckdb_artifact.json")
DEFAULT_TARGET_PATH = Path("data/processed/olist.duckdb")
_MANIFEST_FIELDS = {"version", "url", "size_bytes", "sha256"}
_HASH_CHUNK_SIZE = 1024 * 1024

DownloadFunction = Callable[[str, Path], None]


class ArtifactStagingError(RuntimeError):
    """Raised when a database artifact cannot be staged safely."""


class ManifestError(ArtifactStagingError):
    """Raised when the artifact manifest is missing or invalid."""


@dataclass(frozen=True)
class ArtifactManifest:
    """Validated immutable coordinates for one database artifact."""

    version: str
    url: str
    size_bytes: int
    sha256: str


def load_manifest(path: Path) -> ArtifactManifest:
    """Read and strictly validate the minimal artifact manifest."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"manifest invalid: {exc}") from exc

    if not isinstance(data, dict) or set(data) != _MANIFEST_FIELDS:
        raise ManifestError(
            "manifest invalid: expected exactly version, url, size_bytes, sha256"
        )

    version = data["version"]
    url = data["url"]
    size_bytes = data["size_bytes"]
    sha256 = data["sha256"]

    if not isinstance(version, str) or not version.strip():
        raise ManifestError("manifest invalid: version must be a non-empty string")
    if not isinstance(url, str):
        raise ManifestError("manifest invalid: url must be an HTTPS URL")
    parsed_url = urlparse(url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise ManifestError("manifest invalid: url must be an HTTPS URL")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int):
        raise ManifestError("manifest invalid: size_bytes must be a positive integer")
    if size_bytes <= 0:
        raise ManifestError("manifest invalid: size_bytes must be a positive integer")
    if (
        not isinstance(sha256, str)
        or len(sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in sha256)
    ):
        raise ManifestError("manifest invalid: sha256 must be a 64-character hex digest")

    return ArtifactManifest(
        version=version,
        url=url,
        size_bytes=size_bytes,
        sha256=sha256.lower(),
    )


def _calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        while chunk := artifact.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_matches(path: Path, manifest: ArtifactManifest) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == manifest.size_bytes
        and _calculate_sha256(path) == manifest.sha256
    )


def _download_artifact(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def _verify_download(path: Path, manifest: ArtifactManifest) -> None:
    actual_size = path.stat().st_size
    if actual_size != manifest.size_bytes:
        raise ArtifactStagingError(
            f"size mismatch: expected {manifest.size_bytes}, got {actual_size}"
        )

    actual_sha256 = _calculate_sha256(path)
    if actual_sha256 != manifest.sha256:
        raise ArtifactStagingError(
            f"SHA256 mismatch: expected {manifest.sha256}, got {actual_sha256}"
        )


def stage_database(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    target_path: Path = DEFAULT_TARGET_PATH,
    *,
    downloader: DownloadFunction = _download_artifact,
) -> bool:
    """Verify or atomically stage the database; return whether it was downloaded."""

    manifest = load_manifest(manifest_path)
    if _artifact_matches(target_path, manifest):
        return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=f".{target_path.name}.",
        suffix=".download",
        dir=target_path.parent,
        delete=False,
    )
    temporary_path = Path(temporary_handle.name)
    temporary_handle.close()

    try:
        try:
            downloader(manifest.url, temporary_path)
        except Exception as exc:
            raise ArtifactStagingError(f"download failed: {exc}") from exc
        _verify_download(temporary_path, manifest)
        os.replace(temporary_path, target_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return True


def main() -> int:
    try:
        downloaded = stage_database()
    except ArtifactStagingError as exc:
        print(f"Database artifact staging failed: {exc}", file=sys.stderr)
        return 1

    action = "Staged" if downloaded else "Verified existing"
    print(f"{action} database artifact: {DEFAULT_TARGET_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
