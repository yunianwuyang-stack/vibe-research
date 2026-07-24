from __future__ import annotations

import zipfile

import pytest


def test_archive_rejects_traversal_and_oversized_member_count(tmp_path):
    from services.safe_archive import MAX_ZIP_FILES, extract_zip

    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="Path traversal"):
        extract_zip(traversal, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()

    bomb = tmp_path / "many.zip"
    with zipfile.ZipFile(bomb, "w") as archive:
        for index in range(MAX_ZIP_FILES + 1):
            archive.writestr(f"f{index}.txt", "x")
    with pytest.raises(ValueError, match="limits"):
        extract_zip(bomb, tmp_path / "out-many")


def test_archive_extracts_safe_zip_and_filename_is_flat(tmp_path):
    from services.safe_archive import extract_zip, safe_filename

    source = tmp_path / "safe.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("folder/data.txt", "ok")
    destination = tmp_path / "out"
    assert extract_zip(source, destination) == ["folder/data.txt"]
    assert (destination / "folder" / "data.txt").read_text() == "ok"
    assert safe_filename("document.pdf") == "document.pdf"
    with pytest.raises(ValueError):
        safe_filename("../document.pdf")
