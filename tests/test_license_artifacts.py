import json
from pathlib import Path

def test_sbom_and_notices_are_machine_readable_and_disclose_reference_non_copying():
    root = Path(__file__).resolve().parents[1]
    sbom = json.loads((root / 'SBOM.spdx.json').read_text(encoding='utf-8'))
    notices = (root / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
    assert sbom['spdxVersion'].startswith('SPDX-2.3')
    assert sbom['packages'] and all('name' in package for package in sbom['packages'])
    assert 'No source files, prompts, templates, or assets were copied' in notices
    assert 'academic-research-skills' in notices and 'AutoR' in notices

def test_license_audit_script_rejects_untracked_embedded_credentials_and_missing_artifacts():
    root = Path(__file__).resolve().parents[1]
    script = (root / 'scripts' / 'Test-License.ps1').read_text(encoding='utf-8')
    assert 'THIRD_PARTY_NOTICES.md' in script and 'SBOM.spdx.json' in script
    assert 'access[_-]?token' in script and 'git diff --check' in script


def test_license_audit_allows_python_password_type_annotations_and_runtime_values():
    root = Path(__file__).resolve().parents[1]
    script = (root / 'scripts' / 'Test-License.ps1').read_text(encoding='utf-8')
    assert 'password\\s*:\\s*(?:str|bytes)' in script
    assert 'password\\s*:\\s*[A-Za-z_$]' in script


def test_release_benchmark_uses_asar_unpacked_backend():
    root = Path(__file__).resolve().parents[1]
    script = (root / 'scripts' / 'run_release_benchmarks.py').read_text(encoding='utf-8')
    assert 'install_root / "resources" / "app.asar.unpacked"' in script
