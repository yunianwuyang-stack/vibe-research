from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

import psutil
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.v2.scripts.supervisor import (
    SupervisorConfig,
    SupervisorPolicyError,
    SupervisorSpawnError,
    reconcile_interrupted_progress,
    receipt_succeeded,
    run_supervised,
)
import harness.v2.scripts.supervisor as supervisor_module


def _config(tmp_path: Path, code: str, **overrides) -> SupervisorConfig:
    values = {
        "argv": [sys.executable, "-c", code],
        "cwd": tmp_path,
        "allowed_cwd_roots": [tmp_path],
        "env": {"PYTHONDONTWRITEBYTECODE": "1"},
        "allowed_env_keys": ["PYTHONDONTWRITEBYTECODE"],
        "deadline_seconds": 3.0,
        "heartbeat_seconds": 0.05,
        "graceful_shutdown_seconds": 0.05,
        "stdout_limit_bytes": 64 * 1024,
        "stderr_limit_bytes": 64 * 1024,
    }
    values.update(overrides)
    return SupervisorConfig(**values)


def test_success_receipt_binds_raw_hash_identity_heartbeat_and_cleanup(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt = run_supervised(
        _config(tmp_path, "import sys,time;sys.stdout.buffer.write(b'hello');sys.stdout.flush();time.sleep(.12)"),
        receipt_path=receipt_path,
    )

    assert receipt["termination_reason"] == "EXITED"
    assert receipt["exit_code"] == 0
    assert receipt["stdout"]["raw_sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert receipt["stdout"]["redacted_sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert receipt["stdout"]["redacted_text"] == "hello"
    assert receipt["heartbeats"]
    assert receipt["pid_tree"]
    root = next(item for item in receipt["pid_tree"] if item["pid"] == receipt["root_identity"]["pid"])
    assert root["ppid"] == os.getpid()
    assert root["create_time_epoch"] > 0
    assert root["executable_sha256"] == receipt["root_identity"]["executable_sha256_before_spawn"]
    assert receipt["cleanup"]["orphan_count"] == 0
    assert receipt["cleanup"]["identity_match"] is True
    assert receipt_succeeded(receipt) is True
    tampered = json.loads(json.dumps(receipt))
    tampered["cleanup"]["identity_match"] = False
    assert receipt_succeeded(tampered) is False
    assert receipt["cleanup"]["process_name_cleanup_used"] is False
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
    progress_path = receipt_path.with_name(receipt_path.name + ".progress.json")
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["state"] == "FINALIZED"
    assert progress["heartbeat_chain_head"] == receipt["heartbeat_chain"]["head"]
    assert progress["receipt_sha256"] == hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert reconcile_interrupted_progress(progress_path)["status"] == "FINALIZED"
    if os.name == "nt":
        assert receipt["spawn_boundary"]["kind"] == "windows_suspended_kill_on_close_job"
        assert receipt["spawn_boundary"]["spawn_before_assign_execution_window"] is False
        assert receipt["spawn_boundary"]["kill_on_job_close"] is True
        assert receipt["spawn_boundary"]["resumed_thread_count"] >= 1
    else:
        assert receipt["spawn_boundary"]["kind"] == "posix_process_group"


def test_policy_rejects_string_argv_outside_cwd_and_environment_overreach(tmp_path: Path) -> None:
    outside = tmp_path.parent
    with pytest.raises(SupervisorPolicyError, match="argv_must_be_an_array"):
        SupervisorConfig(
            argv=f"{sys.executable} -c pass",
            cwd=tmp_path,
            allowed_cwd_roots=[tmp_path],
        ).validated()
    with pytest.raises(SupervisorPolicyError, match="cwd_outside_allow_roots"):
        SupervisorConfig(
            argv=[sys.executable, "-c", "pass"],
            cwd=outside,
            allowed_cwd_roots=[tmp_path],
        ).validated()
    with pytest.raises(SupervisorPolicyError, match="environment_key_outside_allowlist"):
        _config(
            tmp_path,
            "pass",
            env={"PYTHONDONTWRITEBYTECODE": "1", "UNEXPECTED": "value"},
        ).validated()


def test_environment_is_explicit_and_secret_output_is_redacted(tmp_path: Path, monkeypatch) -> None:
    secret = "credential-value-that-must-not-appear"
    monkeypatch.setenv("HOST_ONLY_SHOULD_NOT_LEAK", "host-value")
    code = (
        "import os;print(os.environ['SUPER_SECRET']);"
        "print('leaked=' + str('HOST_ONLY_SHOULD_NOT_LEAK' in os.environ))"
    )
    progress_path = tmp_path / "secret-progress.json"
    receipt = run_supervised(
        _config(
            tmp_path,
            code,
            env={
                "PYTHONDONTWRITEBYTECODE": "1",
                "SUPER_SECRET": secret,
            },
            allowed_env_keys=["PYTHONDONTWRITEBYTECODE", "SUPER_SECRET"],
        ),
        progress_path=progress_path,
    )
    serialized = json.dumps(receipt, ensure_ascii=False)
    assert secret not in serialized
    assert "[REDACTED]" in receipt["stdout"]["redacted_text"]
    assert "leaked=False" in receipt["stdout"]["redacted_text"]
    assert "HOST_ONLY_SHOULD_NOT_LEAK" not in receipt["command"]["environment_keys"]
    assert secret not in progress_path.read_text(encoding="utf-8")


def test_secret_crossing_capture_limit_cannot_leave_a_partial_value(tmp_path: Path) -> None:
    secret = "boundary-secret-value-123456789"
    limit = 64
    code = (
        "import os,sys,time;"
        f"sys.stdout.write('x'*{limit - 5}+os.environ['BOUNDARY_SECRET']+'tail');"
        "sys.stdout.flush();time.sleep(30)"
    )
    receipt = run_supervised(
        _config(
            tmp_path,
            code,
            env={"PYTHONDONTWRITEBYTECODE": "1", "BOUNDARY_SECRET": secret},
            allowed_env_keys=["PYTHONDONTWRITEBYTECODE", "BOUNDARY_SECRET"],
            stdout_limit_bytes=limit,
            deadline_seconds=3,
        )
    )
    serialized = json.dumps(receipt, ensure_ascii=False)
    assert receipt["termination_reason"] == "OUTPUT_LIMIT"
    assert secret not in serialized
    assert secret[:8] not in receipt["stdout"]["redacted_text"]
    assert receipt["stdout"]["captured_bytes"] <= limit


@pytest.mark.parametrize(
    ("stream_name", "payload", "limit", "forbidden"),
    [
        ("stdout", "xxxxBearer ABCDEFGHI", 14, "ABC"),
        ("stderr", "xxapi_key=SECRET123", 13, "SEC"),
        ("stdout", 'xx\"token\":\"TOKEN12345\"', 14, "TOK"),
        ("stderr", "xxsk-ABCDEFGH123", 10, "ABC"),
    ],
)
def test_every_truncated_secret_form_omits_the_entire_raw_prefix(
    tmp_path: Path,
    stream_name: str,
    payload: str,
    limit: int,
    forbidden: str,
) -> None:
    code = (
        "import sys;"
        f"stream=sys.{stream_name};stream.write({payload!r});stream.flush()"
    )
    receipt = run_supervised(
        _config(
            tmp_path,
            code,
            stdout_limit_bytes=limit if stream_name == "stdout" else 1024,
            stderr_limit_bytes=limit if stream_name == "stderr" else 1024,
        )
    )
    stream = receipt[stream_name]
    assert receipt["termination_reason"] == "OUTPUT_LIMIT"
    assert stream["limit_exceeded"] is True
    assert forbidden not in stream["redacted_text"]
    assert stream["redacted_text"] == "[OUTPUT OMITTED: BYTE LIMIT EXCEEDED]"[:limit]


def test_streamed_secret_labels_split_across_writes_are_redacted(tmp_path: Path) -> None:
    code = (
        "import sys,time;"
        "sys.stdout.write('Bearer ');sys.stdout.flush();time.sleep(.03);"
        "sys.stdout.write('STREAMSECRET1');sys.stdout.flush();"
        "sys.stderr.write('{\"api_key\":\"');sys.stderr.flush();time.sleep(.03);"
        "sys.stderr.write('STREAMSECRET2\"}');sys.stderr.flush()"
    )
    receipt = run_supervised(
        _config(
            tmp_path,
            code,
            redaction_values=["STREAMSECRET1", "STREAMSECRET2"],
        )
    )
    serialized = json.dumps(receipt, ensure_ascii=False)
    assert receipt_succeeded(receipt) is True
    assert "STREAMSECRET1" not in serialized
    assert "STREAMSECRET2" not in serialized
    assert "[REDACTED]" in receipt["stdout"]["redacted_text"]
    assert "[REDACTED]" in receipt["stderr"]["redacted_text"]


def test_stdout_overflow_cancels_process_and_keeps_capture_bounded(tmp_path: Path) -> None:
    receipt = run_supervised(
        _config(
            tmp_path,
            "import sys,time;sys.stdout.buffer.write(b'x'*200000);sys.stdout.flush();time.sleep(30)",
            deadline_seconds=5,
            stdout_limit_bytes=1024,
        )
    )
    assert receipt["termination_reason"] == "OUTPUT_LIMIT"
    assert receipt["stdout"]["limit_exceeded"] is True
    assert receipt["stdout"]["raw_bytes"] > 1024
    assert receipt["stdout"]["captured_bytes"] <= 1024
    assert receipt["cleanup"]["orphan_count"] == 0
    assert any(
        action["action"] in {"graceful_cancel", "force_cleanup"}
        for action in receipt["cleanup"]["actions"]
    )


def test_timeout_removes_grandchild_that_ignores_graceful_exit(tmp_path: Path) -> None:
    grandchild = (
        "import signal,time;"
        "signal.signal(signal.SIGINT,signal.SIG_IGN);"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "signal.signal(getattr(signal,'SIGBREAK',signal.SIGTERM),signal.SIG_IGN);"
        "time.sleep(60)"
    )
    parent = (
        "import signal,subprocess,sys,time;"
        "signal.signal(signal.SIGINT,signal.SIG_IGN);"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "signal.signal(getattr(signal,'SIGBREAK',signal.SIGTERM),signal.SIG_IGN);"
        f"child=subprocess.Popen([sys.executable,'-c',{grandchild!r}]);"
        "print(child.pid,flush=True);time.sleep(60)"
    )
    receipt = run_supervised(
        _config(tmp_path, parent, deadline_seconds=0.45, heartbeat_seconds=0.03)
    )

    assert receipt["termination_reason"] == "TIMED_OUT"
    assert len(receipt["pid_tree"]) >= 2
    assert receipt["cleanup"]["orphan_count"] == 0
    assert any(action["action"] == "force_cleanup" for action in receipt["cleanup"]["actions"])
    identities = {(item["pid"], item["create_time_epoch"]) for item in receipt["pid_tree"]}
    assert len(identities) == len(receipt["pid_tree"])


def test_external_cancel_and_heartbeat_callback_failure_both_cleanup(tmp_path: Path) -> None:
    cancellation = threading.Event()

    def cancel_after_first(_heartbeat) -> None:
        cancellation.set()

    cancelled = run_supervised(
        _config(tmp_path, "import time;time.sleep(30)"),
        cancel_event=cancellation,
        heartbeat_callback=cancel_after_first,
    )
    assert cancelled["termination_reason"] == "CANCELLED"
    assert cancelled["cleanup"]["orphan_count"] == 0

    def fail_callback(_heartbeat) -> None:
        raise RuntimeError("callback details must not be persisted")

    failed = run_supervised(
        _config(tmp_path, "import time;time.sleep(30)"),
        heartbeat_callback=fail_callback,
    )
    assert failed["termination_reason"] == "HEARTBEAT_CALLBACK_ERROR"
    assert failed["callback_error_type"] == "RuntimeError"
    assert failed["cleanup"]["orphan_count"] == 0


def test_persisted_heartbeat_survives_supervisor_interruption_and_reconciles(
    tmp_path: Path,
) -> None:
    progress_path = tmp_path / "interrupted.progress.json"

    def interrupt_after_persist(_heartbeat) -> None:
        running = json.loads(progress_path.read_text(encoding="utf-8"))
        assert running["state"] == "RUNNING"
        assert running["heartbeats"]
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_supervised(
            _config(tmp_path, "import time;time.sleep(30)"),
            progress_path=progress_path,
            heartbeat_callback=interrupt_after_persist,
        )

    reconciled = reconcile_interrupted_progress(progress_path)
    assert reconciled["status"] == "INTERRUPTED"
    assert reconciled["orphan_count"] == 0
    assert reconciled["heartbeat_count"] >= 1
    assert reconciled["process_name_cleanup_used"] is False


def test_progress_tamper_and_receipt_heartbeat_tamper_fail_closed(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt = run_supervised(
        _config(tmp_path, "import time;time.sleep(.08)"), receipt_path=receipt_path
    )
    tampered_receipt = json.loads(json.dumps(receipt))
    tampered_receipt["heartbeats"][0]["elapsed_seconds"] += 1
    assert receipt_succeeded(tampered_receipt) is False

    progress_path = receipt_path.with_name(receipt_path.name + ".progress.json")
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["heartbeats"][0]["elapsed_seconds"] += 1
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    with pytest.raises(SupervisorPolicyError, match="payload_tampered"):
        reconcile_interrupted_progress(progress_path)


def test_root_identity_observation_failure_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(supervisor_module, "_identity", lambda *_args, **_kwargs: None)
    receipt = run_supervised(_config(tmp_path, "print('must-not-run-before-identity')"))

    assert receipt["termination_reason"] == "IDENTITY_UNAVAILABLE"
    assert receipt["pid_tree"] == []
    assert receipt["cleanup"]["identity_match"] is False
    assert receipt["cleanup"]["orphan_count"] is None
    assert receipt["cleanup"]["identity_failures"] == [
        {
            "pid": receipt["root_identity"]["pid"],
            "stage": "root",
            "reason": "identity_unavailable",
        }
    ]
    assert receipt_succeeded(receipt) is False
    if os.name == "nt":
        assert "must-not-run-before-identity" not in receipt["stdout"]["redacted_text"]


def test_post_cleanup_identity_access_failure_cannot_report_zero_orphans(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        supervisor_module, "_same_process_state", lambda _identity: None
    )
    receipt = run_supervised(_config(tmp_path, "print('completed')"))

    assert receipt["termination_reason"] == "IDENTITY_VERIFICATION_FAILED"
    assert receipt["cleanup"]["identity_match"] is False
    assert receipt["cleanup"]["orphan_count"] is None
    assert receipt["cleanup"]["unknown_identity_checks"]
    assert receipt_succeeded(receipt) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object fault injection")
def test_job_assignment_failure_terminates_exact_suspended_root(tmp_path: Path, monkeypatch) -> None:
    identities: list[tuple[int, float]] = []

    def fail_assignment(_job, pid: int) -> None:
        identities.append((pid, psutil.Process(pid).create_time()))
        raise OSError("injected assignment failure")

    monkeypatch.setattr(supervisor_module._WindowsJob, "assign_pid", fail_assignment)
    with pytest.raises(SupervisorSpawnError, match="failed_to_assign_suspended_process_to_job"):
        run_supervised(_config(tmp_path, "import time;time.sleep(30)"))

    assert identities
    pid, creation_time = identities[0]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            if abs(psutil.Process(pid).create_time() - creation_time) >= 0.01:
                break
        except psutil.NoSuchProcess:
            break
        time.sleep(0.02)
    else:
        pytest.fail("suspended root survived failed Job Object assignment")
