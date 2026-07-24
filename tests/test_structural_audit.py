import json
from pathlib import Path

def test_structural_audit_has_no_new_domain_to_infrastructure_violation(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('structural_audit', Path(__file__).resolve().parents[1] / 'tools' / 'structural_audit.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); audit = module.audit
    root = Path(__file__).resolve().parents[1]
    report = audit(root)
    assert report['passed'] is True
    assert report['domain_infrastructure_imports'] == []
    assert report['new_placeholder_findings'] == []
    assert 'workflow_engine.py' in report['legacy_components']

def test_structural_audit_detects_forbidden_domain_import(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('structural_audit', Path(__file__).resolve().parents[1] / 'tools' / 'structural_audit.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); audit = module.audit
    (tmp_path / 'backend/domain').mkdir(parents=True)
    (tmp_path / 'backend/domain/bad.py').write_text('from infrastructure.x import y\n', encoding='utf-8')
    (tmp_path / 'backend/services').mkdir(parents=True)
    report = audit(tmp_path)
    assert report['passed'] is False
    assert report['domain_infrastructure_imports'] == ['backend/domain/bad.py:1']
