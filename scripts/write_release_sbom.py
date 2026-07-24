#!/usr/bin/env python3
"""Generate deterministic release SBOMs from the compact runtime summary.

The full runtime manifest contains tens of thousands of file hashes and stays
the integrity authority.  This generator intentionally consumes the compact
summary so Windows PowerShell never expands that large array into memory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True, encoding="utf-8"
    ).strip()


def spdx_expression(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or raw == "NOASSERTION":
        return "NOASSERTION"
    if raw.startswith("LicenseRef-"):
        return raw
    if re.fullmatch(r"[A-Za-z0-9.+-]+", raw):
        return raw
    if re.fullmatch(
        r"[()A-Za-z0-9.+\- ]+(?:AND|OR|WITH)[()A-Za-z0-9.+\- ]+", raw
    ):
        return raw
    return "NOASSERTION"


def cyclone_licenses(value: Any) -> list[dict[str, Any]]:
    raw = str(value or "").strip() or "NOASSERTION"
    expression = spdx_expression(raw)
    if expression == "NOASSERTION":
        return [{"license": {"name": raw}}]
    if any(token in expression for token in (" AND ", " OR ", " WITH ", "(")):
        return [{"expression": expression}]
    return [{"license": {"id": expression}}]


def node_inventory(lock_path: Path) -> list[dict[str, str]]:
    lock = read_json(lock_path)
    items: list[dict[str, str]] = []
    for package_path, value in lock.get("packages", {}).items():
        if not package_path or not value.get("version"):
            continue
        name = value.get("name") or package_path.rsplit("node_modules/", 1)[-1]
        items.append(
            {
                "name": str(name),
                "version": str(value["version"]),
                "license": str(value.get("license") or "NOASSERTION"),
                "source": (
                    "frontend/package-lock.json"
                    if lock_path.parent.name == "frontend"
                    else "package-lock.json"
                ),
            }
        )
    return items


def validate_external_adapter_contract(runtime: dict[str, Any]) -> dict[str, Any]:
    """Reject a release summary that confuses external Claude with shipped code."""

    external_adapters = runtime.get("external_adapters")
    if not isinstance(external_adapters, dict):
        raise SystemExit("runtime summary is missing external_adapters")
    claude = external_adapters.get("claude")
    if not isinstance(claude, dict):
        raise SystemExit("runtime summary is missing external_adapters.claude")
    if claude.get("bundled") is not False:
        raise SystemExit("external_adapters.claude.bundled must be boolean false")
    if claude.get("required") is not False:
        raise SystemExit("external_adapters.claude.required must be boolean false")

    for section_name in ("capabilities", "agent_clis"):
        section = runtime.get(section_name) or {}
        if not isinstance(section, dict):
            raise SystemExit(f"runtime summary {section_name} must be an object")
        for name, value in section.items():
            serialized = json.dumps(value, ensure_ascii=False).casefold()
            if str(name).casefold() == "claude" or "@anthropic-ai/claude-code" in serialized:
                raise SystemExit(
                    f"runtime summary incorrectly declares Claude in shipped {section_name}"
                )

    for item in runtime.get("licenses") or []:
        path = str((item or {}).get("path") or "").replace("\\", "/").casefold()
        if "claude" in path:
            raise SystemExit("runtime summary contains a bundled Claude license path")
    return external_adapters


def main(runtime_root: Path | None = None) -> int:
    runtime_root = (runtime_root or (ROOT / "runtime-release")).resolve()
    runtime_manifest = runtime_root / "manifest.json"
    runtime_summary = runtime_root / "manifest.summary.json"
    for required in (
        ROOT / "package.json",
        ROOT / "package-lock.json",
        ROOT / "frontend" / "package-lock.json",
        ROOT / "backend" / "requirements.txt",
        runtime_manifest,
        runtime_summary,
    ):
        if not required.is_file():
            raise SystemExit(f"required SBOM input is missing: {required}")

    package = read_json(ROOT / "package.json")
    runtime = read_json(runtime_summary)
    external_adapters = validate_external_adapter_contract(runtime)
    commit = git("rev-parse", "HEAD")
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if epoch:
        from datetime import datetime, timezone

        generated = datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat()
    else:
        generated = git("show", "-s", "--format=%cI", commit)
    namespace_hash = hashlib.sha256(
        f"Vibe Research|{package['version']}|{commit}".encode("utf-8")
    ).digest()
    deterministic_guid = str(uuid.UUID(bytes_le=namespace_hash[:16]))

    components: list[dict[str, Any]] = []
    component_keys: set[tuple[str, str, str]] = set()

    def add(component: dict[str, Any]) -> None:
        key = (
            str(component["type"]).casefold(),
            str(component["name"]).casefold(),
            str(component["version"]).casefold(),
        )
        if key not in component_keys:
            component_keys.add(key)
            components.append(component)

    for lock in (ROOT / "package-lock.json", ROOT / "frontend" / "package-lock.json"):
        for item in node_inventory(lock):
            add(
                {
                    "type": "library",
                    "name": item["name"],
                    "version": item["version"],
                    "licenses": cyclone_licenses(item["license"]),
                    "properties": [{"name": "vibe:source", "value": item["source"]}],
                }
            )

    for item in runtime.get("python_packages", []):
        add(
            {
                "type": "library",
                "name": str(item.get("name") or "unknown"),
                "version": str(item.get("version") or "unknown"),
                "licenses": cyclone_licenses(item.get("license")),
                "properties": [
                    {"name": "vibe:source", "value": "runtime-release/python"}
                ],
            }
        )

    for name, item in runtime.get("capabilities", {}).items():
        component: dict[str, Any] = {
            "type": "application",
            "name": str(name),
            "version": str(item.get("version") or "unknown"),
            "licenses": cyclone_licenses(item.get("license")),
            "properties": [{"name": "vibe:path", "value": str(item.get("path") or "")}],
        }
        if item.get("sha256"):
            component["hashes"] = [
                {"alg": "SHA-256", "content": str(item["sha256"]).lower()}
            ]
        add(component)

    display_names = {"codex": "OpenAI Codex CLI"}
    for name, item in runtime.get("agent_clis", {}).items():
        properties = [
            {"name": "vibe:path", "value": str(item.get("executable") or "")},
            {
                "name": "vibe:reported-version",
                "value": str(item.get("reported_version") or ""),
            },
            {
                "name": "vibe:redistribution-status",
                "value": str(item.get("redistribution_status") or "not_declared"),
            },
            {"name": "vibe:npm-package", "value": str(item.get("npm_package") or "")},
            {
                "name": "vibe:npm-integrity",
                "value": str(item.get("package_integrity") or ""),
            },
            {
                "name": "vibe:license-files",
                "value": json.dumps(item.get("license_files") or [], separators=(",", ":")),
            },
        ]
        component = {
            "type": "application",
            "name": display_names.get(name, str(name)),
            "version": str(
                item.get("package_version")
                or item.get("reported_version")
                or "unknown"
            ),
            "licenses": cyclone_licenses(item.get("license")),
            "properties": properties,
        }
        if item.get("sha256"):
            component["hashes"] = [
                {"alg": "SHA-256", "content": str(item["sha256"]).lower()}
            ]
        add(component)

    add(
        {
            "type": "application",
            "name": "Vibe Research",
            "version": str(package["version"]),
            "licenses": cyclone_licenses("MIT"),
        }
    )
    add(
        {
            "type": "runtime",
            "name": "Vibe Research portable production runtime",
            "version": str(runtime.get("schema_version") or "unknown"),
            "licenses": cyclone_licenses("NOASSERTION"),
            "properties": [
                {"name": "vibe:files", "value": str(runtime.get("files") or 0)},
                {"name": "vibe:bytes", "value": str(runtime.get("bytes") or 0)},
                {"name": "vibe:manifest-sha256", "value": sha256(runtime_manifest)},
                {"name": "vibe:manifest-summary-sha256", "value": sha256(runtime_summary)},
                {
                    "name": "vibe:requirements-sha256",
                    "value": sha256(ROOT / "backend" / "requirements.txt"),
                },
                {
                    "name": "vibe:release-eligible",
                    "value": str(bool(runtime.get("release_eligible"))).lower(),
                },
                {
                    "name": "vibe:release-blockers",
                    "value": json.dumps(runtime.get("release_blockers") or []),
                },
            ],
        }
    )

    root_ref = ""
    dependency_refs: list[str] = []
    for index, component in enumerate(components, 1):
        component["bom-ref"] = f"urn:vibe:component:{index}"
        if component["name"] == "Vibe Research":
            root_ref = component["bom-ref"]
        else:
            dependency_refs.append(component["bom-ref"])
    if not root_ref:
        raise SystemExit("Vibe Research root component is absent")

    cyclone = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{deterministic_guid}",
        "version": 1,
        "metadata": {
            "timestamp": generated,
            "component": {
                "type": "application",
                "name": "Vibe Research",
                "version": str(package["version"]),
                "bom-ref": root_ref,
            },
            "properties": [
                {"name": "vibe:commit", "value": commit},
                {"name": "vibe:runtime-layout", "value": str(runtime.get("layout") or "")},
                *[
                    {
                        "name": f"vibe:external-adapter:{name}",
                        "value": json.dumps(
                            value,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                    for name, value in sorted(external_adapters.items())
                ],
            ],
        },
        "components": components,
        "dependencies": [{"ref": root_ref, "dependsOn": dependency_refs}],
    }

    spdx_packages: list[dict[str, Any]] = [
        {
            "name": "Vibe Research",
            "SPDXID": "SPDXRef-Package-Root",
            "versionInfo": str(package["version"]),
            "downloadLocation": "NOASSERTION",
            "licenseDeclared": "MIT",
            "licenseConcluded": "MIT",
        }
    ]
    counter = 0
    for component in components:
        if component["name"] == "Vibe Research":
            continue
        counter += 1
        raw_license = "NOASSERTION"
        first_license = (component.get("licenses") or [{}])[0]
        if "expression" in first_license:
            raw_license = first_license["expression"]
        else:
            raw_license = (first_license.get("license") or {}).get("id") or (
                first_license.get("license") or {}
            ).get("name") or "NOASSERTION"
        declared = spdx_expression(raw_license)
        entry: dict[str, Any] = {
            "name": component["name"],
            "SPDXID": f"SPDXRef-Package-{counter}",
            "versionInfo": component["version"],
            "downloadLocation": "NOASSERTION",
            "licenseDeclared": declared,
            "licenseConcluded": declared,
        }
        hashes = component.get("hashes") or []
        if hashes:
            entry["checksums"] = [
                {
                    "algorithm": "SHA256",
                    "checksumValue": str(hashes[0]["content"]),
                }
            ]
        spdx_packages.append(entry)

    relationships = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": "SPDXRef-Package-Root",
        }
    ]
    relationships.extend(
        {
            "spdxElementId": "SPDXRef-Package-Root",
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": item["SPDXID"],
        }
        for item in spdx_packages
        if item["SPDXID"] != "SPDXRef-Package-Root"
    )
    spdx: dict[str, Any] = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "Vibe Research Workbench",
        "documentNamespace": (
            f"https://vibe-research.local/spdx/{package['version']}/{deterministic_guid}"
        ),
        "creationInfo": {
            "created": generated,
            "creators": ["Tool: Vibe Research release metadata generator"],
        },
        "packages": spdx_packages,
        "relationships": relationships,
    }
    (ROOT / "SBOM.cdx.json").write_text(
        json.dumps(cyclone, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "SBOM.spdx.json").write_text(
        json.dumps(spdx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "cyclone_components": len(components),
                "cyclone_dependencies": len(dependency_refs),
                "spdx_packages": len(spdx_packages),
                "spdx_relationships": len(relationships),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    import sys

    selected_runtime = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    raise SystemExit(main(selected_runtime))
