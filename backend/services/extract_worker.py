"""(docstring)"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional
from xml.etree import ElementTree

log = logging.getLogger(__name__)

_STATUS_FILE = "_extract_status.json"
_STATUS_VERSION = 2


_GLOBAL_SEMAPHORE = asyncio.Semaphore(4)


_inflight: dict[str, asyncio.Task] = {}
_inflight_lock = asyncio.Lock()


def _status_path(upload_dir: Path | str) -> Path:
    """(docstring)"""
    return Path(upload_dir) / _STATUS_FILE


def _load_status(upload_dir: Path | str) -> dict:
    """(docstring)"""
    p = _status_path(upload_dir)
    if not p.exists():
        return {"version": _STATUS_VERSION, "files": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("version", 0) < _STATUS_VERSION:
            data["version"] = _STATUS_VERSION
            data["files"] = {}
        return data
    except Exception:
        return {"version": _STATUS_VERSION, "files": {}}


def _save_status(upload_dir: Path | str, status: dict) -> None:
    """(docstring)"""
    p = _status_path(upload_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_status(upload_dir: Path | str, name: str, **fields) -> None:
    """(docstring)"""
    status = _load_status(upload_dir)
    file_status = status.setdefault("files", {}).setdefault(name, {})
    file_status.update(fields)
    _save_status(upload_dir, status)


def get_status(upload_dir: Path | str) -> dict:
    """(docstring)"""
    return _load_status(upload_dir)


def mark_pending(upload_dir: Path | str, name: str) -> None:
    """(docstring)"""
    _update_status(upload_dir, name, status="pending", started_at=None, finished_at=None)


async def _run_extract(upload_dir: Path, name: str) -> None:
    """(docstring)"""
    _update_status(upload_dir, name, status="running", started_at=time.time())

    filepath = upload_dir / name
    try:
        text = await extract_text_file(filepath)

        if text is not None:

            text_path = upload_dir / (name + ".txt")
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(text, encoding="utf-8")
            _update_status(upload_dir, name, status="completed", finished_at=time.time(),
                           text_file=text_path.relative_to(upload_dir).as_posix(), chars=len(text))
        else:
            _update_status(upload_dir, name, status="skipped", finished_at=time.time(),
                           reason="Unsupported file type or no text extracted")

    except Exception as e:
        log.error("Extract failed for %s: %s", name, e)
        _update_status(upload_dir, name, status="failed", finished_at=time.time(), error=str(e))


def _office_xml_text(filepath: Path, members: list[str]) -> str:
    chunks: list[str] = []
    with zipfile.ZipFile(filepath) as archive:
        names = set(archive.namelist())
        for member in members:
            if member not in names:
                continue
            root = ElementTree.fromstring(archive.read(member))
            current: list[str] = []
            for node in root.iter():
                tag = node.tag.rsplit("}", 1)[-1]
                if tag in {"t", "v"} and node.text:
                    current.append(node.text)
                elif tag in {"p", "tr", "row"} and current:
                    chunks.append("".join(current))
                    current = []
            if current:
                chunks.append("".join(current))
    return "\n".join(item for item in chunks if item.strip())


def _docx_text(filepath: Path) -> str:
    with zipfile.ZipFile(filepath) as archive:
        members = [
            name for name in archive.namelist()
            if name == "word/document.xml"
            or re.fullmatch(r"word/(header|footer)\d+\.xml", name)
            or name in {"word/footnotes.xml", "word/endnotes.xml"}
        ]
        paragraphs: list[str] = []
        for member in members:
            root = ElementTree.fromstring(archive.read(member))
            for paragraph in (node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "p"):
                text = "".join(
                    node.text or ""
                    for node in paragraph.iter()
                    if node.tag.rsplit("}", 1)[-1] in {"t", "tab", "br"}
                ).strip()
                if text:
                    paragraphs.append(text)
    return "\n".join(paragraphs)


def _xlsx_text(filepath: Path) -> str:
    with zipfile.ZipFile(filepath) as archive:
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in (node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "si"):
                shared.append("".join(
                    node.text or "" for node in item.iter()
                    if node.tag.rsplit("}", 1)[-1] == "t"
                ))
        rows: list[str] = []
        worksheets = sorted(
            name for name in names
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        for sheet_index, member in enumerate(worksheets, 1):
            root = ElementTree.fromstring(archive.read(member))
            sheet_rows: list[str] = []
            for row in (node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "row"):
                values: list[str] = []
                for cell in (node for node in row if node.tag.rsplit("}", 1)[-1] == "c"):
                    cell_type = cell.attrib.get("t", "")
                    value_node = next((node for node in cell.iter() if node.tag.rsplit("}", 1)[-1] == "v"), None)
                    if cell_type == "inlineStr":
                        value = "".join(
                            node.text or "" for node in cell.iter()
                            if node.tag.rsplit("}", 1)[-1] == "t"
                        )
                    else:
                        value = value_node.text if value_node is not None and value_node.text else ""
                        if cell_type == "s" and value.isdigit() and int(value) < len(shared):
                            value = shared[int(value)]
                    values.append(value)
                if any(value.strip() for value in values):
                    sheet_rows.append("\t".join(values))
            if sheet_rows:
                rows.extend([f"[Sheet {sheet_index}]", *sheet_rows])
    return "\n".join(rows)


async def extract_text_file(filepath: Path) -> str | None:
    """Extract searchable text without requiring optional Office libraries."""
    suffix = filepath.suffix.lower()
    if suffix == ".pdf":
        try:
            import fitz  # type: ignore
            document = fitz.open(str(filepath))
            try:
                return "\n".join(page.get_text() for page in document)
            finally:
                document.close()
        except ImportError:
            try:
                from PyPDF2 import PdfReader  # type: ignore
                return "\n".join(page.extract_text() or "" for page in PdfReader(str(filepath)).pages)
            except ImportError:
                log.warning("No PDF library available for extraction")
                return None
    if suffix in {".docx", ".dotx"}:
        return await asyncio.to_thread(_docx_text, filepath)
    if suffix in {".xlsx", ".xlsm"}:
        return await asyncio.to_thread(_xlsx_text, filepath)
    if suffix in {
        ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".ipynb",
        ".bib", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".tex", ".cls", ".sty",
        ".py", ".r", ".m", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".cc",
        ".cpp", ".h", ".hpp", ".go", ".rs", ".sql", ".sh", ".ps1", ".html", ".htm", ".xml",
    }:
        return filepath.read_text(encoding="utf-8", errors="replace")
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}:
        try:
            from services.llm_client import describe_image
            return await describe_image(str(filepath), context=f"Image file: {filepath.name}")
        except Exception as error:
            log.warning("Image description failed for %s: %s", filepath.name, error)
    return None


async def schedule_extract(upload_dir: Path | str, name: str) -> None:
    """(docstring)"""
    upload_dir = Path(upload_dir)
    key = str(upload_dir / name)

    async with _inflight_lock:
        if key in _inflight and not _inflight[key].done():
            return

        async def _wrapped():
            async with _GLOBAL_SEMAPHORE:
                await _run_extract(upload_dir, name)

            async with _inflight_lock:
                _inflight.pop(key, None)

        task = asyncio.create_task(_wrapped())
        _inflight[key] = task
