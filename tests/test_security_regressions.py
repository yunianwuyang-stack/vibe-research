from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_port_selection_never_kills_unknown_processes():
 source=(ROOT/'main.js').read_text(encoding='utf8');start=source.index('async function findAvailablePort');end=source.index('function getMiKTeXDir',start)
 assert 'taskkill' not in source[start:end] and 'netstat' not in source[start:end]
def test_editor_generic_script_execution_is_not_available():
 assert 'Generic script execution is unavailable' in (ROOT/'backend/routers/editor.py').read_text(encoding='utf8')
