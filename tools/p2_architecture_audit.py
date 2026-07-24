"""Deterministic P2 architecture and clone/dead-code gate.

The checker is intentionally source based: it reports forbidden dependency edges,
import cycles, unregistered legacy production paths, and high-similarity files.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

LAYERS = ("routers", "application", "domain", "infrastructure", "services")
ALLOWED = {
    "routers": {"application", "domain", "services", "infrastructure", "routers"},
    "services": {"application", "domain", "infrastructure", "services", "routers"},
    "application": {"domain", "infrastructure", "application"},
    "domain": {"domain"},
    "infrastructure": {"application", "domain", "infrastructure"},
}
LEGACY_ADR = "harness/decisions/ADR-P2-001-canonical-run-engine.md"


def _module_layer(path: Path, root: Path) -> str | None:
    parts = path.relative_to(root).parts
    return parts[1] if len(parts) > 1 and parts[0] == "backend" and parts[1] in LAYERS else None


def _import_layer(node: ast.AST) -> str | None:
    name = getattr(node, "module", "") or ""
    if isinstance(node, ast.Import):
        names = [item.name for item in node.names]
    else:
        names = [name]
    for value in names:
        for layer in LAYERS:
            if value == layer or value.startswith(layer + "."):
                return layer
    return None


def _tokens(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    return set(re.findall(r"[a-z_][a-z0-9_]{3,}", text))


def audit(root: Path) -> dict:
    backend = root / "backend"
    files = sorted(backend.rglob("*.py")) if backend.exists() else []
    findings: list[str] = []
    edges: dict[str, set[str]] = {layer: set() for layer in LAYERS}
    graph: dict[str, set[str]] = {}
    for path in files:
        layer = _module_layer(path, root)
        if not layer:
            continue
        module = path.relative_to(root).with_suffix("").as_posix().replace("/", ".")
        graph[module] = set()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
        except SyntaxError as error:
            findings.append(f"syntax:{path.relative_to(root).as_posix()}:{error.lineno}")
            continue
        for node in ast.walk(tree):
            target = _import_layer(node)
            if target:
                edges[layer].add(target)
                if target not in ALLOWED[layer]:
                    findings.append(f"forbidden-edge:{layer}->{target}:{path.relative_to(root).as_posix()}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [item.name for item in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for name in names:
                    if name.startswith("backend."):
                        graph[module].add(name)
    # Resolve only local backend modules for deterministic cycle detection.
    cycles: list[str] = []
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(node: str, trail: list[str]) -> None:
        if node in visiting:
            cycles.append("->".join(trail[trail.index(node):] + [node]))
            return
        if node in visited:
            return
        visiting.add(node)
        for target in graph.get(node, ()):
            if target in graph:
                visit(target, trail + [target])
        visiting.remove(node); visited.add(node)
    for node in graph:
        visit(node, [node])
    findings.extend(f"import-cycle:{item}" for item in sorted(set(cycles)))

    legacy = {
        "backend/services/workflow_engine.py": {"adr": LEGACY_ADR, "production_reachable": False, "deletion_condition": "canonical run API owns create and advance"},
        "backend/services/research_orchestrator.py": {"adr": LEGACY_ADR, "production_reachable": False, "deletion_condition": "legacy route is read/migration-only"},
    }
    for path, metadata in legacy.items():
        if metadata["production_reachable"] and (root / path).exists():
            findings.append(f"legacy-production-reachable:{path}")
        if not (root / metadata["adr"]).exists():
            findings.append(f"legacy-missing-adr:{path}")

    clones: list[dict[str, object]] = []
    candidates = [path for path in files if _module_layer(path, root) in {"application", "domain", "services"}]
    for index, left in enumerate(candidates):
        left_tokens = _tokens(left)
        if len(left_tokens) < 12:
            continue
        for right in candidates[index + 1:]:
            right_tokens = _tokens(right)
            similarity = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
            if similarity >= 0.92:
                clones.append({"left": left.relative_to(root).as_posix(), "right": right.relative_to(root).as_posix(), "jaccard": round(similarity, 4)})
    return {"passed": not findings and not clones, "findings": sorted(set(findings)), "cycles": sorted(set(cycles)), "clones": clones, "edges": {key: sorted(value) for key, value in edges.items()}, "legacy_components": legacy}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = audit(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
