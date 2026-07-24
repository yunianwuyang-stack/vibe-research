"""Progressive, metadata-only discovery for bundled skills."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _value(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    if text.startswith(("[", "{", '"')):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    return text


def _frontmatter(text: str) -> dict[str, Any]:
    """Parse the small YAML-compatible subset used by SKILL manifests."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: dict[str, Any] = {}
    current_list: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        list_item = re.match(r"^\s*-\s+(.+)$", line)
        if list_item and current_list:
            metadata.setdefault(current_list, []).append(_value(list_item.group(1)))
            continue
        pair = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not pair:
            continue
        key, raw = pair.groups()
        if raw.strip():
            metadata[key] = _value(raw)
            current_list = None
        else:
            metadata[key] = []
            current_list = key
    return metadata


def _as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def discover(skills_root: Path) -> dict:
    """Return metadata only; prompt bodies are never included in the response."""
    skills_root = Path(skills_root)
    skills = []
    seen = set()
    if not skills_root.is_dir():
        return {"schema_version": "1.0", "count": 0, "skills": []}
    for directory in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file() or directory.name in seen:
            continue
        seen.add(directory.name)
        data = skill_file.read_bytes()
        text = data.decode("utf-8", errors="replace")
        metadata = _frontmatter(text)
        title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        required = _as_list(metadata.get("required_capabilities", metadata.get("capabilities")))
        input_schema = metadata.get("input_schema", metadata.get("input", "arguments"))
        output_schema = metadata.get("output_schema", metadata.get("output", "workspace artifacts"))
        skills.append({
            "id": directory.name,
            "name": str(metadata.get("name") or (title_match.group(1).strip() if title_match else directory.name)),
            "description": str(metadata.get("description", "")),
            "version": str(metadata.get("version", "local")),
            "source": "bundled",
            "owner": str(metadata.get("owner", "unknown")),
            "license": str(metadata.get("license", "unknown")),
            "dependencies": _as_list(metadata.get("dependencies")),
            "required_capabilities": required,
            "required_capability": required[0] if len(required) == 1 else None,
            "input": input_schema,
            "output": output_schema,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "manifest_status": "declared" if metadata else "inferred",
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return {"schema_version": "1.0", "count": len(skills), "skills": skills}
