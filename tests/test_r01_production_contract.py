from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_source_layout_never_targets_adjacent_legacy_web_checkout():
 config=(ROOT/"backend"/"config.py").read_text(encoding="utf8")
 main=(ROOT/"main.js").read_text(encoding="utf8")
 assert 'PROJECT_ROOT / "runtime" / "workspaces"' in config
 assert 'resolve_product_db_path(PROJECT_ROOT / "runtime" / "backend")' in config
 assert 'PRODUCT_DB_NAME = "vibe.db"' in config
 assert "path.join(EXECUTABLE_APP_ROOT, 'backend')" in main
 assert "'..', 'web', 'backend'" not in main
