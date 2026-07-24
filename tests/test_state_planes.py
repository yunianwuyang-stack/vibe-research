from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def test_state_planes_never_equate_completed_with_verified():
    from services.state_planes import project_state_planes
    state = project_state_planes({"status": "completed"})
    assert state["execution"] == "succeeded"
    assert state["assurance"] == "pending"
    assert state["root_cause"] == "assurance_not_yet_verified"


def test_state_planes_preserve_transport_root_cause():
    from services.state_planes import project_state_planes
    state = project_state_planes({"status": "failed", "error_message": "provider timeout"})
    assert state["transport"] == "failed"
    assert state["execution"] == "failed"
    assert state["assurance"] == "blocked"
    assert "timeout" in state["root_cause"]
