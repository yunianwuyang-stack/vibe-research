from pathlib import Path
import importlib.util

_spec = importlib.util.spec_from_file_location("p2_architecture_audit", Path(__file__).resolve().parents[1] / "tools" / "p2_architecture_audit.py")
_module = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_module)
audit = _module.audit


def test_p2_architecture_gate_passes_for_repository():
    report = audit(Path(__file__).resolve().parents[1])
    assert report["passed"] is True, report
    assert report["cycles"] == []
    assert report["clones"] == []


def test_p2_architecture_gate_detects_forbidden_layer_edge(tmp_path):
    domain = tmp_path / "backend" / "domain"
    domain.mkdir(parents=True)
    (domain / "bad.py").write_text("from infrastructure.db import connect\n", encoding="utf-8")
    report = audit(tmp_path)
    assert report["passed"] is False
    assert any(item.startswith("forbidden-edge:domain->infrastructure") for item in report["findings"])
