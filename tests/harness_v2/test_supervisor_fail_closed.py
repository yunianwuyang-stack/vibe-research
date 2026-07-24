import pytest

from harness.v2.supervisor import HarnessError, project_state, transition, write_checkpoint


def test_failure_state_never_projects_pass(tmp_path):
    transition(tmp_path, state="IN_PROGRESS", task_id="P0.0", phase="P0.0", next_action="run checker")
    transition(tmp_path, state="BLOCKED", task_id="P0.0", phase="P0.0", failure="injected")
    assert project_state(tmp_path)["status"] == "BLOCKED"


def test_invalid_state_is_rejected(tmp_path):
    with pytest.raises(HarnessError):
        transition(tmp_path, state="INVALID", task_id="P0.0", phase="P0.0", next_action="run checker")


def test_checkpoint_requires_action(tmp_path):
    with pytest.raises(HarnessError):
        write_checkpoint(tmp_path, {"phase": "P0.0", "status": "CHECKPOINTED", "next_action": "continue reading"})
