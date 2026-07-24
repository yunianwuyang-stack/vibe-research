from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from harness.v2.scripts import frontend_cache


ROOT = Path(__file__).parents[1]


def test_default_frontend_commands_use_runner_config_loader() -> None:
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["test"] == "vitest run --configLoader runner"
    assert package["scripts"]["build"] == "vite build --configLoader runner"


def test_default_frontend_commands_do_not_name_source_tree_vite_temp() -> None:
    package_text = (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    assert ".vite-temp" not in package_text


def test_source_manifest_is_content_bound_and_excludes_generated_roots(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.ts").write_text("alpha", encoding="utf-8")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("generated", encoding="utf-8")
    first = frontend_cache._manifest(tmp_path, excluded_top_level={"dist"})
    (tmp_path / "dist" / "bundle.js").write_text("changed generated", encoding="utf-8")
    assert frontend_cache._manifest(tmp_path, excluded_top_level={"dist"}) == first
    (tmp_path / "src" / "main.ts").write_text("beta", encoding="utf-8")
    assert frontend_cache._manifest(tmp_path, excluded_top_level={"dist"}) != first


def test_default_script_drift_fails_closed(tmp_path: Path) -> None:
    package = {
        "scripts": {
            "test": "vitest run",
            "build": "vite build --configLoader runner",
        }
    }
    (tmp_path / "package.json").write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(frontend_cache.FrontendCacheError, match="script drift"):
        frontend_cache._load_default_scripts(tmp_path)


def test_temp_projection_copies_dependencies_without_source_cache(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "src").mkdir(parents=True)
    (source / "src" / "main.ts").write_text("source", encoding="utf-8")
    (source / "dist").mkdir()
    (source / "dist" / "bundle.js").write_text("old", encoding="utf-8")
    (source / "node_modules" / "package-a").mkdir(parents=True)
    (source / "node_modules" / "package-a" / "index.js").write_text(
        "module", encoding="utf-8"
    )
    (source / "node_modules" / ".vite").mkdir()
    (source / "node_modules" / ".vite" / "cache").write_text("cache", encoding="utf-8")
    (source / "node_modules" / ".vite-temp").mkdir()
    (source / "node_modules" / ".vite-temp" / "loader").write_text(
        "loader", encoding="utf-8"
    )

    frontend_cache._copy_projection(source, target)

    assert (target / "src" / "main.ts").read_text(encoding="utf-8") == "source"
    assert (target / "node_modules" / "package-a" / "index.js").is_file()
    assert not (target / "dist").exists()
    assert not (target / "node_modules" / ".vite").exists()
    assert not (target / "node_modules" / ".vite-temp").exists()


def test_attempt_evidence_replays_and_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_attempt = (
        ROOT / "harness" / "v2" / "evidence" / "P0" / "P0-FRONTEND-CACHE" / "attempt-3"
    )
    attempt = tmp_path / "attempt"
    shutil.copytree(source_attempt, attempt)
    observation = json.loads((attempt / "observation.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        frontend_cache,
        "_assert_protected_cache_unwritable",
        lambda _path: observation["protected_cache"],
    )

    assert frontend_cache.validate_evidence(ROOT, attempt) == observation

    receipt_path = attempt / "npm-test.supervisor.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["cleanup"]["orphan_count"] = 1
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(frontend_cache.FrontendCacheError, match="tampered"):
        frontend_cache.validate_evidence(ROOT, attempt)
