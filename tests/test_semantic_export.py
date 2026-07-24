import sqlite3
from infrastructure.persistence.semantic_export import restore_snapshot, semantic_export

def test_semantic_export_is_stable_and_restore_is_replayable(tmp_path):
    source=tmp_path/"legacy.sqlite3"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, payload TEXT)")
        db.execute("INSERT INTO blobs VALUES (?,?)", ("b1", "用户数据")); db.commit()
    before=semantic_export(source); backup=tmp_path/"backup.sqlite3"
    import shutil; shutil.copy2(source,backup); target=tmp_path/"restored.sqlite3"
    after=restore_snapshot(backup,target)
    assert before["sha256"] == after["sha256"]
