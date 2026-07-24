from pathlib import Path

def test_electron_window_is_sandboxed_and_restricts_navigation_and_permissions():
    source = (Path(__file__).resolve().parents[1] / 'main.js').read_text(encoding='utf-8')
    assert 'sandbox: true' in source
    assert 'contextIsolation: true' in source and 'nodeIntegration: false' in source
    assert 'setPermissionRequestHandler' in source
    assert 'will-navigate' in source and 'isTrustedExternalUrl' in source
    assert 'Content-Security-Policy' in source

def test_packaging_config_is_locked_and_runtime_manifest_is_generated():
    root = Path(__file__).resolve().parents[1]
    import json
    package = json.loads((root / 'package.json').read_text(encoding='utf-8'))
    script = (root / 'scripts' / 'Build-Release.ps1').read_text(encoding='utf-8')
    assert 'electron-builder' in package['devDependencies']
    assert package['build']['asar'] is True
    assert 'backend{,/**}' in package['build']['asarUnpack']
    assert 'dist{,/**}' in package['build']['asarUnpack']
    assert 'package-lock.json' in script and 'runtime-manifest.json' in script
    assert 'Assert-ReleasePayloadPolicy' in script
