from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "config.py"


def load_config():
    spec = importlib.util.spec_from_file_location("config_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_layout_source_mode_has_no_runtime(tmp_path):
    config = load_config()
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    layout = config.RuntimeLayoutResolver(backend, {}).resolve()
    assert layout.source_mode is True
    assert layout.app_root == backend.parent
    assert layout.runtime_root is None


def test_runtime_layout_packaged_mode_discovers_sibling_runtime(tmp_path):
    config = load_config()
    backend = tmp_path / "app" / "backend"
    runtime = tmp_path / "runtime"
    backend.mkdir(parents=True)
    runtime.mkdir()
    layout = config.RuntimeLayoutResolver(backend, {"VIBE_DESKTOP": "1"}).resolve()
    assert layout.source_mode is False
    assert layout.app_root == backend.parent
    assert layout.runtime_root == runtime


def test_runtime_layout_missing_override_is_explicitly_unavailable(tmp_path):
    config = load_config()
    backend = tmp_path / "app" / "backend"
    backend.mkdir(parents=True)
    layout = config.RuntimeLayoutResolver(backend, {"VIBE_RUNTIME_ROOT": str(tmp_path / "missing")}).resolve()
    assert layout.runtime_root is None
    assert layout.source_mode is False

def test_release_package_uses_minimal_runtime_staging():
    import json
    root=SOURCE.parents[1]
    package=json.loads((root/'package.json').read_text(encoding='utf-8'))
    runtime=next(item for item in package['build']['extraResources'] if item['to']=='runtime')
    assert runtime['from']=='runtime-release'
    assert 'New-MinimalRuntime.ps1' in (root/'scripts/Build-Release.ps1').read_text(encoding='utf-8')
    assert 'PYTHONPATH: BACKEND_DIR' in (root/'main.js').read_text(encoding='utf-8')
