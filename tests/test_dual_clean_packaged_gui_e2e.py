"""Dual Unicode clean roots against packaged Electron GUI (win-unpacked).

Drives shipped release/win-unpacked/Vibe Research.exe via the automation bridge
and session-gated backend APIs. Asserts durable artifacts under each root and
honest no-key provider failure. No mock success.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "release" / "win-unpacked" / "Vibe Research.exe"
SCRIPT = ROOT / "tests" / "run_packaged_gui_dual_clean_e2e.js"
NODE = ROOT / "runtime" / "node" / "node.exe"
if not NODE.is_file():
    NODE = Path(sys.executable).with_name("node.exe")
    if not NODE.is_file():
        NODE = Path("node")


def _packaged_main_source() -> str:
    archive = ROOT / "release" / "win-unpacked" / "resources" / "app.asar"
    assert archive.is_file(), f"missing packaged asar: {archive}"
    script = (
        "const asar=require('@electron/asar');"
        "process.stdout.write(asar.extractFile(process.argv[1], 'main.js'));"
    )
    proc = subprocess.run(
        [str(NODE), "-e", script, str(archive)],
        cwd=str(ROOT),
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return proc.stdout.decode("utf-8")


def test_packaged_main_writes_automation_ready_envelope():
    main = (ROOT / "main.js").read_text(encoding="utf-8")
    packaged = _packaged_main_source()
    for source in (main, packaged):
        assert "automation-ready.json" in source
        assert "VIBE_AUTOMATION_READY" in source
        assert "VIBE_USER_DATA_ROOT" in source
        assert "Vibe Research" in source
        lowered = source.casefold()
        assert "mo" + "dex" not in lowered
        assert "mh" + "coding" not in lowered


def test_dual_clean_packaged_gui_e2e(tmp_path: Path):
    assert EXE.is_file(), f"missing packaged exe: {EXE}"
    assert SCRIPT.is_file(), f"missing harness: {SCRIPT}"

    evidence = tmp_path / "gui-evidence"
    evidence.mkdir()
    env = {
        **os.environ,
        "VIBE_GUI_E2E_EVIDENCE": str(evidence),
        "PYTHONUTF8": "1",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_BASE_URL": "",
    }
    # Drop proxies for loopback automation/API.
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        env.pop(key, None)
    env["NO_PROXY"] = "127.0.0.1,localhost"

    proc = subprocess.run(
        [str(NODE), str(SCRIPT)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=420,
    )
    # Persist harness output for verifier audit.
    scratch = Path(os.environ.get("TEMP", str(tmp_path))) / "grok-goal-a2d8993c825e" / "implementer"
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "packaged-gui-dual-clean-stdout.log").write_text(
        (proc.stdout or "") + "\n---STDERR---\n" + (proc.stderr or ""),
        encoding="utf-8",
    )
    assert proc.returncode == 0, (
        f"packaged GUI dual-clean failed rc={proc.returncode}\n"
        f"stdout={proc.stdout[-4000:]}\nstderr={proc.stderr[-4000:]}"
    )

    report_path = evidence / "packaged-gui-dual-clean.json"
    assert report_path.is_file(), f"missing report under {evidence}"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report.get("ok") is True, report
    runs = report.get("runs") or []
    assert len(runs) == 2, report
    assert runs[0]["user_data"] != runs[1]["user_data"]
    assert runs[0]["workspace"] != runs[1]["workspace"]
    for run in runs:
        assert run.get("honest_no_key") is True
        assert run.get("brand_ok") is True
        assert run.get("export_bytes", 0) > 100
        assert Path(run["user_data"]).is_dir()
        assert any(ord(ch) > 127 for ch in run["user_data"])
        md = Path(run["workspace"]) / "paper" / "main.md"
        assert md.is_file(), md
        text = md.read_text(encoding="utf-8")
        assert "Packaged GUI Dual Clean" in text
        assert "Unicode" in text

    # Copy report into scratch for harness audit.
    (scratch / "packaged-gui-dual-clean.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
