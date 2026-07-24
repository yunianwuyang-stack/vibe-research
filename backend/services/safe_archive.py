"""Constrained upload and archive extraction helpers."""
from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path

MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
MAX_ZIP_FILES = 20_000
MAX_ZIP_UNCOMPRESSED = 512 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200


def within(root: Path, candidate: Path) -> Path:
    root = root.resolve()
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path traversal detected") from exc
    return candidate


def safe_filename(name: str) -> str:
    candidate = Path(name)
    if (
        not name
        or candidate.name != name
        or name in {".", ".."}
        or any(character in name for character in '\x00<>:"/\\|?*')
        or name.rstrip(" .") != name
    ):
        raise ValueError("Unsafe upload filename")
    return name


def safe_relative_path(name: str) -> Path:
    """Validate a browser-supplied relative path without flattening folders."""
    normalized = str(name or "").replace("\\", "/").strip("/")
    if not normalized or len(normalized) > 1024:
        raise ValueError("Unsafe upload path")
    parts = normalized.split("/")
    if len(parts) > 32 or any(not part or part in {".", ".."} for part in parts):
        raise ValueError("Unsafe upload path")
    for part in parts:
        safe_filename(part)
    return Path(*parts)


def is_supported_archive(path: Path) -> bool:
    name = path.name.lower()
    return path.suffix.lower() == ".zip" or name.endswith((".tar.gz", ".tgz", ".tar"))


def extract_zip(source: Path, destination: Path) -> list[str]:
    extracted: list[str] = []
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        total_size = sum(item.file_size for item in infos)
        if len(infos) > MAX_ZIP_FILES or total_size > MAX_ZIP_UNCOMPRESSED:
            raise ValueError("ZIP archive exceeds extraction limits")
        for info in infos:
            if info.file_size > MAX_ZIP_UNCOMPRESSED:
                raise ValueError("ZIP member exceeds extraction limits")
            if info.compress_size and info.file_size / info.compress_size > MAX_ZIP_COMPRESSION_RATIO:
                raise ValueError("ZIP member compression ratio exceeds limit")
            target = within(destination, destination / info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as inp, target.open("wb") as out:
                shutil.copyfileobj(inp, out)
            extracted.append(str(target.relative_to(destination)).replace("\\", "/"))
    return extracted


def extract_tar(source: Path, destination: Path) -> list[str]:
    """Extract regular TAR members while rejecting links and special files."""
    extracted: list[str] = []
    with tarfile.open(source, mode="r:*") as archive:
        members = archive.getmembers()
        regular = [member for member in members if member.isfile()]
        if len(members) > MAX_ZIP_FILES or sum(max(member.size, 0) for member in regular) > MAX_ZIP_UNCOMPRESSED:
            raise ValueError("TAR archive exceeds extraction limits")
        for member in members:
            if member.isdir():
                if member.name.replace("\\", "/").strip("/") in {"", "."}:
                    continue
                target = within(destination, destination / safe_relative_path(member.name))
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError("TAR archive contains unsupported link or special file")
            target = within(destination, destination / safe_relative_path(member.name))
            target.parent.mkdir(parents=True, exist_ok=True)
            source_file = archive.extractfile(member)
            if source_file is None:
                raise ValueError("TAR archive member cannot be read")
            with source_file, target.open("wb") as output:
                shutil.copyfileobj(source_file, output)
            extracted.append(str(target.relative_to(destination)).replace("\\", "/"))
    return extracted


def extract_archive(source: Path, destination: Path) -> list[str]:
    if source.suffix.lower() == ".zip":
        return extract_zip(source, destination)
    if source.name.lower().endswith((".tar.gz", ".tgz", ".tar")):
        return extract_tar(source, destination)
    raise ValueError("Unsupported archive format")
