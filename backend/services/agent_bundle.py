"""Discover and attest the official Agent CLI executables.

Packaged desktop builds resolve the immutable runtime manifest before looking
at the host.  A missing or modified bundled executable is therefore surfaced
as a broken installation rather than silently falling back to an unrelated
program on ``PATH``.  Codex is the redistributable bundled adapter; Claude is
always discovered as an optional user-managed installation through an explicit
override or ``PATH`` and is never read from the runtime manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ADAPTERS = {
    "codex": {
        "command": "codex",
        "environment": "CODEX_BIN",
        "install_url": "https://developers.openai.com/codex/cli/",
        "license": "Apache-2.0",
        "bundle_policy": "required",
    },
    "claude": {
        "command": "claude",
        "environment": "CLAUDE_BIN",
        "install_url": "https://docs.anthropic.com/en/docs/claude-code/overview",
        "license": "LicenseRef-Anthropic-Claude-Code-Legal-Agreements",
        "bundle_policy": "external_optional",
    },
}


def _version(executable: str | None) -> str | None:
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0][:200] if result.returncode == 0 and lines else None


def _sha256(path: str | os.PathLike[str] | None) -> str | None:
    candidate = Path(path) if path else None
    if not candidate or not candidate.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _default_runtime_root() -> Path | None:
    override = os.environ.get("VIBE_RUNTIME_ROOT", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_dir():
            return None
        # Electron source mode also points at the developer runtime so its
        # Python/toolchain can be used.  Only an installed application must
        # fail closed when the signed CLI manifest is absent.
        if (candidate / "agent-cli-manifest.json").is_file() or os.environ.get("VIBE_PACKAGED_RUNTIME") == "1":
            return candidate.resolve()
        return None
    try:
        from config import RUNTIME_NODE
    except (ImportError, AttributeError):
        return None
    return Path(RUNTIME_NODE).resolve().parent if RUNTIME_NODE else None


def _read_bundle_manifest(runtime_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    path = runtime_root / "agent-cli-manifest.json"
    if not path.is_file():
        return None, "agent_cli_manifest_missing"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "agent_cli_manifest_invalid"
    if value.get("schema_version") != "1.0" or not isinstance(value.get("adapters"), dict):
        return None, "agent_cli_manifest_schema_invalid"
    if value.get("credential_material_included") is not False:
        return None, "agent_cli_manifest_credential_attestation_invalid"
    return value, None


def _manifest_entry(runtime_root: Path, name: str, value: dict[str, Any]) -> dict[str, Any]:
    spec = ADAPTERS[name]
    relative = str(value.get("executable") or "")
    expected_hash = str(value.get("sha256") or "").lower()
    expected_version = str(value.get("reported_version") or "")
    candidate = (runtime_root / Path(relative)).resolve() if relative else runtime_root
    try:
        candidate.relative_to(runtime_root.resolve())
    except ValueError:
        return _broken_bundle(name, spec, "executable_outside_runtime")
    if not relative or not candidate.is_file():
        return _broken_bundle(name, spec, "bundled_executable_missing")
    expected_bytes = value.get("bytes")
    if not isinstance(expected_bytes, int) or candidate.stat().st_size != expected_bytes:
        return _broken_bundle(name, spec, "bundled_executable_size_mismatch")
    actual_hash = _sha256(candidate)
    if len(expected_hash) != 64 or actual_hash != expected_hash:
        return _broken_bundle(name, spec, "bundled_executable_hash_mismatch")
    actual_version = _version(str(candidate))
    if not actual_version:
        return _broken_bundle(name, spec, "bundled_executable_version_probe_failed")
    if expected_version and actual_version != expected_version:
        return _broken_bundle(name, spec, "bundled_executable_version_mismatch")
    license_records = list(value.get("license_files") or [])
    for component in value.get("bundled_components") or []:
        if not isinstance(component, dict):
            return _broken_bundle(name, spec, "bundled_component_record_invalid")
        license_records.extend(component.get("license_files") or [])
    license_files: list[dict[str, Any]] = []
    for item in license_records:
        if not isinstance(item, dict):
            return _broken_bundle(name, spec, "bundled_license_record_invalid")
        relative_license = str(item.get("path") or "")
        expected_license_hash = str(item.get("sha256") or "").lower()
        license_path = (runtime_root / Path(relative_license)).resolve() if relative_license else runtime_root
        try:
            license_path.relative_to(runtime_root.resolve())
        except ValueError:
            return _broken_bundle(name, spec, "bundled_license_outside_runtime")
        if not relative_license or not license_path.is_file():
            return _broken_bundle(name, spec, "bundled_license_missing")
        actual_license_hash = _sha256(license_path)
        if len(expected_license_hash) != 64 or actual_license_hash != expected_license_hash:
            return _broken_bundle(name, spec, "bundled_license_hash_mismatch")
        expected_license_bytes = item.get("bytes")
        if not isinstance(expected_license_bytes, int) or license_path.stat().st_size != expected_license_bytes:
            return _broken_bundle(name, spec, "bundled_license_size_mismatch")
        license_files.append({
            "path": relative_license,
            "sha256": actual_license_hash,
            "bytes": license_path.stat().st_size,
        })
    if not license_files:
        return _broken_bundle(name, spec, "bundled_license_records_missing")
    return {
        "status": "available",
        "reason": None,
        "executable": str(candidate),
        "version": actual_version,
        "sha256": actual_hash,
        "bytes": candidate.stat().st_size,
        "source": "bundled_manifest",
        "bundled": True,
        "required": spec.get("bundle_policy") == "required",
        "integrity_status": "verified",
        "auth_status": "unknown",
        "redistribution": value.get("redistribution_status") or "not_declared",
        "license": value.get("license") or spec["license"],
        "license_files": license_files,
        "package": {
            "name": value.get("npm_package"),
            "version": value.get("package_version"),
            "integrity": value.get("package_integrity"),
            "platform_name": value.get("platform_package"),
            "platform_version": value.get("platform_version"),
            "platform_integrity": value.get("platform_integrity"),
        },
        "action": {
            "kind": "official_login",
            "url": spec["install_url"],
            "optional": True,
        },
    }


def _broken_bundle(name: str, spec: dict[str, str], reason: str) -> dict[str, Any]:
    return {
        "status": "invalid",
        "reason": reason,
        "executable": None,
        "version": None,
        "sha256": None,
        "bytes": None,
        "source": "bundled_manifest",
        "bundled": True,
        "required": spec.get("bundle_policy") == "required",
        "integrity_status": "failed",
        "auth_status": "unknown",
        "redistribution": "unknown",
        "license": spec["license"],
        "license_files": [],
        "package": None,
        "action": {"kind": "repair_installation", "url": spec["install_url"]},
    }


def _host_entry(
    name: str,
    spec: dict[str, str],
    configured_override: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    configured = os.fspath(configured_override).strip() if configured_override else ""
    if not configured:
        configured = os.environ.get(spec["environment"], "").strip()
    executable: str | None = None
    source: str | None = None
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            executable, source = str(path.resolve()), "environment"
        else:
            resolved = shutil.which(configured)
            if resolved:
                executable, source = resolved, "environment"
    if not executable:
        executable = shutil.which(spec["command"])
        source = "path" if executable else None
    version = _version(executable)
    available = bool(executable and version)
    return {
        "status": "available" if available else "unavailable",
        "reason": None if available else "executable_not_found_or_version_probe_failed",
        "executable": executable if available else None,
        "version": version if available else None,
        "sha256": _sha256(executable) if available else None,
        "bytes": Path(executable).stat().st_size if available and Path(executable).is_file() else None,
        "source": source,
        "bundled": False,
        "required": spec.get("bundle_policy") == "required",
        "integrity_status": "observed" if available else "unavailable",
        "auth_status": "unknown",
        "redistribution": "not_bundled",
        "license": spec["license"],
        "license_files": [],
        "package": None,
        "action": (
            {"kind": "official_login", "url": spec["install_url"], "optional": True}
            if available
            else {"kind": "official_install", "url": spec["install_url"]}
        ),
    }


def build_adapter_manifest(
    runtime_root: str | os.PathLike[str] | None = None,
    configured_overrides: Mapping[str, str | os.PathLike[str]] | None = None,
) -> dict[str, Any]:
    """Return an observable CLI inventory without reading credentials."""
    root = Path(runtime_root).resolve() if runtime_root is not None else _default_runtime_root()
    adapters: dict[str, dict[str, Any]] = {}
    bundle_manifest: dict[str, Any] | None = None
    bundle_error: str | None = None
    if root is not None:
        bundle_manifest, bundle_error = _read_bundle_manifest(root)
    for name, spec in ADAPTERS.items():
        override = configured_overrides.get(name) if configured_overrides else None
        # Claude is a user-managed optional adapter in packaged builds.  It is
        # never accepted from the immutable runtime manifest and its absence
        # must not invalidate the redistributable Codex bundle.
        if spec.get("bundle_policy") == "external_optional":
            adapters[name] = _host_entry(name, spec, override)
            continue
        if root is None:
            adapters[name] = _host_entry(name, spec, override)
            continue
        if bundle_error:
            adapters[name] = _broken_bundle(name, spec, bundle_error)
            continue
        raw = bundle_manifest["adapters"].get(name) if bundle_manifest else None
        adapters[name] = (
            _manifest_entry(root, name, raw)
            if isinstance(raw, dict)
            else _broken_bundle(name, spec, "adapter_missing_from_bundle_manifest")
        )
    embedded = [
        {
            "name": name,
            "path": entry["executable"],
            "version": entry["version"],
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
            "license": entry["license"],
            "redistribution": entry["redistribution"],
            "integrity_status": entry["integrity_status"],
        }
        for name, entry in adapters.items()
        if entry["status"] == "available" and entry["bundled"]
    ]
    bundle_status = "not_applicable"
    if root is not None:
        required_names = {
            name for name, spec in ADAPTERS.items()
            if spec.get("bundle_policy") == "required"
        }
        bundle_status = (
            "invalid"
            if bundle_error or any(
                adapters[name]["status"] != "available" or not adapters[name]["bundled"]
                for name in required_names
            )
            else "verified"
        )
    return {
        "schema_version": "2.0",
        "runtime_root": str(root) if root is not None else None,
        "bundle_manifest_status": bundle_status,
        "adapters": adapters,
        "embedded_binaries": embedded,
    }
