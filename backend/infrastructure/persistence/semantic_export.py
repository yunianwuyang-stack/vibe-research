"""Stable semantic export and restore helpers for legacy SQLite migration drills."""
from __future__ import annotations
import hashlib, json, shutil, sqlite3
from pathlib import Path

def semantic_export(database_path: str | Path) -> dict:
    path=Path(database_path)
    with sqlite3.connect(path) as db:
        tables=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        data={}
        for table in tables:
            columns=[row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
            rows=[dict(zip(columns,row)) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
            data[table]=rows
    encoded=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
    return {"tables":data,"sha256":hashlib.sha256(encoded.encode()).hexdigest()}

def restore_snapshot(snapshot_path: str | Path, database_path: str | Path) -> dict:
    source=Path(snapshot_path); target=Path(database_path); target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target)
    return semantic_export(target)
