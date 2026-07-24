from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterator


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import atomic_write_json


PATTERNS = {
    "openai_key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "github_token": re.compile(rb"\bgh[oprsu]_[A-Za-z0-9]{20,}\b"),
    "aws_access_key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "jwt": re.compile(rb"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
}
# Bundled runtimes are immutable third-party distribution payloads. They are
# inventory/release-audited separately; source scanning covers maintained code
# and configuration, where a credential would be actionable by this project.
SKIP_DIRS = {".git", "node_modules", "release", "runtime", "runtime-release", "dist", "build", "__pycache__"}
SKIP_SUFFIXES = {
    ".7z", ".a", ".avi", ".bin", ".bmp", ".bz2", ".class", ".dll", ".doc", ".docx",
    ".dylib", ".eot", ".exe", ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg", ".lib",
    ".mov", ".mp3", ".mp4", ".o", ".obj", ".otf", ".pdf", ".png", ".ppt", ".pptx", ".pyc",
    ".so", ".tar", ".tif", ".tiff", ".ttc", ".ttf", ".wav", ".webp", ".woff", ".woff2",
    ".xls", ".xlsx", ".xz", ".zip",
}


def files(root: Path) -> Iterator[Path]:
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        names[:] = [name for name in names if name not in SKIP_DIRS]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            if path.suffix.lower() in SKIP_SUFFIXES or path.is_symlink():
                continue
            try:
                if path.stat().st_size <= 10 * 1024 * 1024:
                    yield path
            except OSError:
                continue


def scan(root: Path) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    scanned = 0
    for path in files(root):
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in content[:8192]:
            continue
        scanned += 1
        for pattern_name, pattern in PATTERNS.items():
            for match in pattern.finditer(content):
                value = match.group(0)
                line = content.count(b"\n", 0, match.start()) + 1
                findings.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "line": line,
                        "kind": pattern_name,
                        "fingerprint": hashlib.sha256(value).hexdigest()[:16],
                        "handled": False,
                    }
                )
    return {
        "schema_version": "1.0",
        "scanned_files": scanned,
        "high_risk_findings": len(findings),
        "unhandled_high_risk": sum(not item["handled"] for item in findings),
        "findings": findings,
        "verdict": "PASS" if not findings else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = scan(args.root.resolve())
    atomic_write_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key != "findings"}, sort_keys=True))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
