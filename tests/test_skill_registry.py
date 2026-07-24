from pathlib import Path


def test_skill_registry_is_metadata_only_and_canonical(tmp_path):
    from services.skill_registry import discover
    for name in ("alpha", "beta"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "SKILL.md").write_text(f"# {name}", encoding="utf-8")
    registry = discover(tmp_path)
    assert registry["count"] == 2
    assert [item["id"] for item in registry["skills"]] == ["alpha", "beta"]
    assert all(item["sha256"] and item["source"] == "bundled" for item in registry["skills"])
