from __future__ import annotations

from test_golden_path_http_e2e import free_port, request, server, stop


def test_http_experiment_runs_replays_and_recovers_after_restart(tmp_path):
    token = "experiment-http-token"
    appdata = tmp_path / "appdata"
    port = free_port()
    process = server(port, token, appdata)
    try:
        status, project = request(port, token, "/api/research-projects", "POST", {"title": "Experiment project", "research_question": "Does treatment change outcome?", "inclusion_criteria": "numeric observations"})
        assert status == 200
        status, run = request(port, token, f"/api/experiments/projects/{project['id']}", "POST", {"control": [1, 2, 3], "treatment": [2, 4, 6], "seeds": 3, "metric": "score"})
        assert status == 200 and run["status"] == "completed" and run["statistics"]["passed"]
        status, replay = request(port, token, f"/api/experiments/{run['id']}/replay", "POST")
        assert status == 200 and replay["reproduced"] is True
    finally:
        stop(process)
    port = free_port()
    process = server(port, token, appdata)
    try:
        status, runs = request(port, token, f"/api/experiments/projects/{project['id']}")
        assert status == 200 and len(runs) == 2 and all(item["result_sha256"] == run["result_sha256"] for item in runs)
        status, invalid = request(port, token, f"/api/experiments/projects/{project['id']}", "POST", {"control": [1, "NaN"], "treatment": [2, 3], "seeds": 3, "metric": "score"})
        assert status == 422
    finally:
        stop(process)
