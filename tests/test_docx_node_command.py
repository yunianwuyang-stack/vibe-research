from pathlib import Path


def test_node_docx_cli_uses_named_arguments():
    source = (Path(__file__).parents[1] / "backend" / "routers" / "docx_export.py").read_text(encoding="utf-8")
    assert '"--source", str(source)' in source
    assert '"--output", str(output_path)' in source
    assert '"--workspace", str(workspace)' in source
    assert '"--profile", str(profile)' in source
