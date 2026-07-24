from __future__ import annotations

import pytest

from domain.experiments.manifest import ExecutionSpec, artifact_is_accepted


def _spec(**changes):
    value = {
        "dataset_snapshot": {"sha256": "a" * 64, "uri": "input.json"},
        "environment_lock": {"python": "3.12", "lock_sha256": "b" * 64},
        "command": ("python", "analysis.py"),
        "seeds": (1, 2),
        "hardware": {"platform": "windows", "cpu": "local"},
        "result_schema": {"type": "object", "required": ["difference"]},
    }
    value.update(changes)
    return ExecutionSpec(**value)


def test_simulated_execution_cannot_be_constructed():
    with pytest.raises(ValueError, match="simulated execution is disabled"):
        _spec(simulated=True)


def test_artifact_requires_real_hash_bound_completion():
    spec = _spec()
    assert not artifact_is_accepted(spec=spec, artifact={"status": "completed", "result": {}})
    assert artifact_is_accepted(
        spec=spec,
        artifact={
            "status": "completed",
            "simulated": False,
            "specification_hash": spec.specification_hash,
            "raw_output_sha256": "c" * 64,
            "exit_code": 0,
            "result": {"difference": 2.0, "runs": [
                {"seed": 1, "status": "completed", "raw_output_sha256": "c" * 64},
                {"seed": 2, "status": "completed", "raw_output_sha256": "c" * 64},
            ]},
        },
    )


def test_specification_hash_changes_when_seed_changes():
    assert _spec().specification_hash != _spec(seeds=(1, 3)).specification_hash


def test_hash_or_result_tamper_is_rejected():
    spec = _spec()
    accepted = {"status":"completed", "simulated":False, "exit_code":0, "specification_hash":spec.specification_hash, "raw_output_sha256":"c"*64, "result":{"difference":2.0, "runs":[
        {"seed":1,"status":"completed","raw_output_sha256":"c"*64},
        {"seed":2,"status":"completed","raw_output_sha256":"c"*64}]}}
    assert artifact_is_accepted(spec=spec, artifact=accepted)
    assert not artifact_is_accepted(spec=spec, artifact={**accepted, "specification_hash":"d"*64})
    assert not artifact_is_accepted(spec=spec, artifact={**accepted, "result":{"difference":2.0, "runs":[]}})
