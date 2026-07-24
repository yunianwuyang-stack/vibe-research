import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.v2 import supervisor_p3


def test_timeout_is_checkpointed_and_never_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(supervisor_p3, "ROOT", tmp_path)
    monkeypatch.setattr(supervisor_p3, "STATE", tmp_path / "state" / "current.json")
    monkeypatch.setattr(supervisor_p3, "JOURNAL", tmp_path / "journal.jsonl")
    code = supervisor_p3.run_lane([sys.executable, "-c", "import time; time.sleep(2)"], timeout_seconds=0)
    state = json.loads((tmp_path / "state" / "current.json").read_text(encoding="utf-8"))
    assert code == 124
    assert state["status"] == "CHECKPOINTED"
    assert state["status"] != "PASS"
