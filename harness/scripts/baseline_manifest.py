from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import stat
import sys
from pathlib import Path
from typing import Iterator


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import atomic_write_json, canonical_json, sha256_file


def iter_files(root: Path) -> Iterator[Path]:
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        names.sort(key=str.casefold)
        files.sort(key=str.casefold)
        base = Path(directory)
        for filename in files:
            path = base / filename
            if path.is_symlink():
                continue
            yield path


def file_record(root: Path, path: Path) -> dict[str, object]:
    metadata = path.stat()
    return {
        "path": path.relative_to(root).as_posix(),
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "mode": stat.S_IMODE(metadata.st_mode),
        "sha256": sha256_file(path),
    }


def build(root: Path, output: Path, workers: int) -> dict[str, object]:
    root = root.resolve()
    paths = list(iter_files(root))
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".partial")
    total_bytes = 0
    count = 0
    with temp.open("wb") as handle:
        header = {"type": "header", "schema_version": "1.0", "root": str(root), "file_count": len(paths)}
        handle.write(canonical_json(header) + b"\n")
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for record in executor.map(lambda item: file_record(root, item), paths, chunksize=16):
                handle.write(canonical_json({"type": "file", **record}) + b"\n")
                count += 1
                total_bytes += int(record["size"])
        trailer = {"type": "trailer", "file_count": count, "total_bytes": total_bytes}
        handle.write(canonical_json(trailer) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, output)
    summary = {
        "schema_version": "1.0",
        "root": str(root),
        "manifest": str(output),
        "manifest_sha256": sha256_file(output),
        "file_count": count,
        "total_bytes": total_bytes,
    }
    atomic_write_json(output.with_suffix(output.suffix + ".summary.json"), summary)
    return summary


def read_records(path: Path) -> tuple[dict[str, object], dict[str, dict[str, object]], dict[str, object]]:
    header: dict[str, object] | None = None
    trailer: dict[str, object] | None = None
    records: dict[str, dict[str, object]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            item = json.loads(line)
            kind = item.pop("type")
            if kind == "header":
                if header is not None:
                    raise ValueError("duplicate_header")
                header = item
            elif kind == "file":
                name = str(item["path"])
                if name in records:
                    raise ValueError(f"duplicate_path:{name}")
                records[name] = item
            elif kind == "trailer":
                trailer = item
            else:
                raise ValueError(f"unknown_record:{line_number}")
    if header is None or trailer is None:
        raise ValueError("missing_header_or_trailer")
    if trailer.get("file_count") != len(records):
        raise ValueError("file_count_mismatch")
    return header, records, trailer


def compare(left: Path, right: Path) -> dict[str, object]:
    _, left_records, left_trailer = read_records(left)
    _, right_records, right_trailer = read_records(right)
    all_paths = sorted(set(left_records) | set(right_records), key=str.casefold)
    differences: list[dict[str, object]] = []
    for name in all_paths:
        left_item = left_records.get(name)
        right_item = right_records.get(name)
        if left_item is None or right_item is None:
            differences.append({"path": name, "kind": "missing"})
        elif left_item["size"] != right_item["size"] or left_item["sha256"] != right_item["sha256"]:
            differences.append({"path": name, "kind": "content"})
        if len(differences) >= 100:
            break
    return {
        "verdict": "PASS" if not differences else "FAIL",
        "left_count": len(left_records),
        "right_count": len(right_records),
        "left_bytes": left_trailer["total_bytes"],
        "right_bytes": right_trailer["total_bytes"],
        "differences": differences,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "compare"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--left", type=Path)
    parser.add_argument("--right", type=Path)
    parser.add_argument("--workers", type=int, default=max(2, min(8, os.cpu_count() or 2)))
    args = parser.parse_args()
    if args.command == "build":
        if not args.root or not args.output:
            parser.error("build requires --root and --output")
        result = build(args.root, args.output, args.workers)
        result["verdict"] = "PASS"
    else:
        if not args.left or not args.right:
            parser.error("compare requires --left and --right")
        result = compare(args.left, args.right)
        if args.output:
            atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
