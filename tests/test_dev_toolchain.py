from pathlib import Path


def test_dev_toolchain_is_separate_from_bundled_runtime():
    root = Path(__file__).resolve().parents[1]
    requirements = (root / "requirements-dev.txt").read_text(encoding="utf-8")
    script = (root / "scripts" / "Test-Dev.ps1").read_text(encoding="utf-8")
    assert "pytest==" in requirements and "ruff==" in requirements and "mypy==" in requirements
    assert ".venv-dev" in script
    assert "runtime" not in script.lower()
