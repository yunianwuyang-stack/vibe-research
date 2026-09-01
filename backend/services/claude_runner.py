"""(docstring)"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import signal
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from config import (
    IS_DESKTOP,
    CLAUDE_BIN,
    PANDOC_BIN,
    RUNTIME_PYTHON,
    RUNTIME_NODE,
    RUNTIME_TEXLIVE,
    RUNTIME_DRAWIO,
    SKILLS_DIR,
    TOOLS_DIR,
)

log = logging.getLogger(__name__)

REVIEWER_SCRIPT = str(TOOLS_DIR / "reviewer_client.py")
SCHOLAR_SCRIPT = str(TOOLS_DIR / "scholar_fetch.py")
_ACTIVE_RESPONSES_AGENTS: Dict[str, Any] = {}
_ACTIVE_CLAUDE_PROCESSES: Dict[str, asyncio.subprocess.Process] = {}
_ACTIVE_EXECUTIONS_LOCK = threading.RLock()

_AGENT_BASE_ENV_ALLOWLIST = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "HOME", "USERPROFILE"}

def _minimal_agent_environment(source: Dict[str, str], *, role_prefix: str = "EXECUTOR_") -> Dict[str, str]:
    return {key: str(value) for key, value in source.items() if key in _AGENT_BASE_ENV_ALLOWLIST or key.startswith(role_prefix) or key.startswith("VIBE_RUNTIME_")}



# ``extra_params`` is shown to the model, but a number of shipped skills also
# consume direct variable aliases from shell commands. Keep the stable
# ``SKILL_*`` namespace while exporting only this reviewed
# set of direct aliases.  This prevents a visible workflow option from being a
# prompt-only hint and keeps arbitrary extension fields out of the unprefixed
# process environment.
_DIRECT_SKILL_ENV_ALIASES = {
    "max_pages": "MAX_PAGES",
    "min_figures": "MIN_FIGURES",
    "min_tables": "MIN_TABLES",
    "min_models": "MIN_MODELS",
    "output_format": "OUTPUT_FORMAT",
    "competition": "COMPETITION",
    "paper_type": "PAPER_TYPE",
    "column_layout": "COLUMN_LAYOUT",
    "figure_style": "FIGURE_STYLE",
    "flowchart_engine": "FLOWCHART_ENGINE",
    "word_count_target": "WORD_COUNT_TARGET",
    "max_rounds": "MAX_ROUNDS",
    "target_score": "TARGET_SCORE",
    "TARGET_VENUE": "TARGET_VENUE",
    # Competition / academic options consumed by shipped SKILL.md files as
    # unprefixed shell variables (in addition to SKILL_* and the prompt dump).
    "tools": "TOOLS",
    "problem_id": "PROBLEM_ID",
    "custom_title": "CUSTOM_TITLE",
    "language": "LANGUAGE",
    "subject_domain": "SUBJECT_DOMAIN",
    "degree_level": "DEGREE_LEVEL",
    "cn_en_ratio": "CN_EN_RATIO",
    "target_paper_count": "TARGET_PAPER_COUNT",
    "format_text": "FORMAT_TEXT",
    "paper_type_target": "PAPER_TYPE_TARGET",
    "paper_branch": "PAPER_BRANCH",
    # One-sentence project / IP workflows consume these aliases from shell
    # checks and CLAUDE.md scaffolding.
    "project_type": "PROJECT_TYPE",
    "tech_frontend": "TECH_FRONTEND",
    "tech_backend": "TECH_BACKEND",
    "tech_db": "TECH_DB",
    "tech_lang": "TECH_LANG",
    "design_style": "DESIGN_STYLE",
    "design_style_custom": "DESIGN_STYLE_CUSTOM",
    "feature_requirements": "FEATURE_REQUIREMENTS",
    "software_name": "SOFTWARE_NAME",
    "software_version": "SOFTWARE_VERSION",
    "case_name": "CASE_NAME",
}


def _environment_scalar(value: Any) -> Optional[str]:
    """Convert a validated workflow scalar to a shell-friendly value."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _skill_parameter_environment(extra_params: Optional[Dict]) -> Dict[str, str]:
    """Build the shared Responses/Claude environment for workflow options."""
    if not extra_params:
        return {}

    environment: Dict[str, str] = {}
    for key, value in extra_params.items():
        # Preserve the historical namespace consumed by third-party skills.
        environment[f"SKILL_{str(key).upper()}"] = str(value)

    for parameter, alias in _DIRECT_SKILL_ENV_ALIASES.items():
        if parameter not in extra_params:
            continue
        value = extra_params[parameter]
        # "auto" means the model plans the quantity; it must not look like a
        # numeric hard lower bound to shell checks.
        if parameter in {"min_figures", "min_tables", "min_models"} and value == "auto":
            continue
        scalar = _environment_scalar(value)
        if scalar is not None:
            environment[alias] = scalar

    validation_mode = str(extra_params.get("validation_mode") or "").strip().lower()
    if validation_mode:
        fast = "1" if validation_mode == "fast" else "0"
        environment["VALIDATION_MODE"] = validation_mode
        environment["FAST_MODE"] = fast
        environment["VIBE_FAST_MODE"] = fast

    if "rich_mode" in extra_params:
        scalar = _environment_scalar(extra_params.get("rich_mode"))
        if scalar is not None:
            environment["RICH_MODE"] = scalar

    return environment


def _register_active_execution(registry: Dict[str, Any], workflow_id: str, value: Any) -> str:
    """Register an execution without replacing an already-running sibling.

    Duplicate keys are uncommon in the normal sequential workflow engine, but
    can occur when a restart races the final cleanup of a cancelled step.  A
    plain assignment followed by an unconditional ``pop`` lets the older run
    hide (and later delete) the newer run, making process-tree cancellation
    unreliable exactly when it is needed most.
    """
    with _ACTIVE_EXECUTIONS_LOCK:
        key = workflow_id
        suffix = 2
        while key in registry:
            key = f"{workflow_id}#{suffix}"
            suffix += 1
        registry[key] = value
        return key


def _unregister_active_execution(registry: Dict[str, Any], key: str, value: Any) -> None:
    """Remove only the registration still owned by ``value``."""
    with _ACTIVE_EXECUTIONS_LOCK:
        if registry.get(key) is value:
            registry.pop(key, None)


def _prepare_skill_runtime(cwd: Union[str, Path]) -> Dict[str, str]:
    """Materialize and validate the executor capabilities promised to skills.

    Skills invoke shared helpers through _utils and external helper scripts
    through environment variables. Missing helpers are a blocked capability,
    not an invitation for the model to improvise or silently skip validation.
    """
    workspace = Path(cwd).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    capabilities = {
        "reviewer": Path(REVIEWER_SCRIPT),
        "scholar": Path(SCHOLAR_SCRIPT),
    }
    for name, path in capabilities.items():
        if not path.is_file():
            raise RuntimeError(f"CAPABILITY_BLOCKED:{name}:script_not_found:{path}")

    from services.skill_crypto import decrypt_skills_to_workspace

    try:
        mounted = decrypt_skills_to_workspace(
            SKILLS_DIR,
            workspace,
            sub_dir="shared-scripts",
            destination_sub_dir="_utils",
        )
    except Exception as exc:
        raise RuntimeError(f"CAPABILITY_BLOCKED:shared-scripts:mount_failed:{exc}") from exc
    utils_dir = workspace / "_utils"
    if not mounted or not utils_dir.is_dir() or not any(utils_dir.iterdir()):
        raise RuntimeError(
            f"CAPABILITY_BLOCKED:shared-scripts:not_found_or_empty:{SKILLS_DIR / 'shared-scripts'}"
        )

    python_command = _python_command_name()
    if not python_command:
        raise RuntimeError("CAPABILITY_BLOCKED:python:not_configured_or_not_found")
    return {
        "REVIEWER_SCRIPT": str(capabilities["reviewer"].resolve()),
        "SCHOLAR_SCRIPT": str(capabilities["scholar"].resolve()),
        "PYTHON": python_command,
        "VIBE_SKILL_UTILS": str(utils_dir),
    }


def _mount_skill_support(skill_name: str, cwd: Union[str, Path]) -> Optional[Path]:
    """Expose one skill's references inside the bounded Responses workspace."""
    source = SKILLS_DIR / skill_name
    if not source.is_dir():
        return None
    from services.skill_crypto import decrypt_skill_md, decrypt_skills_to_workspace

    # A dot-prefixed mount stays out of workflow artifact snapshots while
    # remaining readable by the bounded workspace tools.
    destination = f".vibe-skills/{skill_name}"
    mounted = decrypt_skills_to_workspace(
        SKILLS_DIR,
        Path(cwd).resolve(),
        sub_dir=skill_name,
        destination_sub_dir=destination,
    )
    target = Path(cwd).resolve() / destination
    if not mounted or not target.is_dir():
        raise RuntimeError(f"CAPABILITY_BLOCKED:skill-support:mount_failed:{skill_name}")

    content = decrypt_skill_md(SKILLS_DIR, skill_name) or ""
    dependencies = set(
        re.findall(r"\$CLAUDE_SKILL_DIR/\.\./([A-Za-z0-9_.-]+)", content)
    )
    if (SKILLS_DIR / "shared-references").is_dir():
        dependencies.add("shared-references")
    for dependency in sorted(dependencies):
        if not (SKILLS_DIR / dependency).is_dir():
            continue
        dependency_mounted = decrypt_skills_to_workspace(
            SKILLS_DIR,
            Path(cwd).resolve(),
            sub_dir=dependency,
            destination_sub_dir=f".vibe-skills/{dependency}",
        )
        if not dependency_mounted:
            raise RuntimeError(
                f"CAPABILITY_BLOCKED:skill-support:dependency_mount_failed:{dependency}"
            )
    return target


def _runtime_bin_directories() -> List[str]:
    """Return existing bundled runtime directories in deterministic order."""
    candidates: List[Path] = []
    if RUNTIME_NODE:
        node_root = Path(RUNTIME_NODE)
        candidates.extend([node_root, node_root / "bin"])
    if RUNTIME_PYTHON:
        python_root = Path(RUNTIME_PYTHON).parent
        candidates.extend([python_root, python_root / "Scripts"])
    detected_python = globals().get("_DETECTED_PYTHON")
    if detected_python:
        detected_path = Path(str(detected_python))
        if detected_path.is_file():
            candidates.append(detected_path.parent)
    if RUNTIME_TEXLIVE:
        tex_root = Path(RUNTIME_TEXLIVE)
        candidates.extend([
            tex_root / "texmfs" / "install" / "miktex" / "bin" / "x64",
            tex_root / "bin" / "windows",
            tex_root / "miktex" / "bin" / "x64",
            tex_root / "bin",
        ])
    if RUNTIME_DRAWIO:
        drawio_root = Path(RUNTIME_DRAWIO)
        candidates.extend([drawio_root, drawio_root / "bin"])
    if PANDOC_BIN:
        candidates.append(Path(PANDOC_BIN).parent)

    directories: List[str] = []
    seen = set()
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        resolved = str(candidate.resolve())
        key = os.path.normcase(resolved)
        if key not in seen:
            seen.add(key)
            directories.append(resolved)
    return directories


def _augment_runtime_path(env: Dict[str, str]) -> Dict[str, str]:
    """Prepend bundled tool directories while preserving the host PATH."""
    bundled = _runtime_bin_directories()
    current = env.get("PATH", "")
    env["PATH"] = os.pathsep.join(bundled + ([current] if current else []))
    return env


def _detect_python() -> Optional[str]:
    """Locate a usable Python interpreter using the installed runner's search order."""
    candidates: List[str] = []
    if RUNTIME_PYTHON:
        candidates.append(str(RUNTIME_PYTHON))
    if sys.executable:
        candidates.append(sys.executable)

    checked_candidates: List[str] = []
    for candidate in candidates:
        if Path(candidate).exists():
            checked_candidates.append(candidate)

    system = platform.system()
    if system == "Windows":
        home = Path.home()
        for version in ("313", "312", "311", "310", "39", "38"):
            for candidate in (
                str(home / "AppData" / "Local" / "Programs" / "Python" / f"Python{version}" / "python.exe"),
                f"C:\\Python{version}\\python.exe",
                f"C:\\Program Files\\Python{version}\\python.exe",
            ):
                if Path(candidate).exists():
                    checked_candidates.append(candidate)

    path_commands = ("py", "python", "python3") if system == "Windows" else ("python", "python3")
    for command in path_commands:
        found = shutil.which(command)
        if found:
            if command == "py":
                # Resolve the Windows launcher to the selected interpreter so
                # the exported PYTHON value remains a real executable path.
                try:
                    selected = subprocess.run(
                        [found, "-3", "-c", "import sys; print(sys.executable)"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    selected_path = selected.stdout.strip()
                    if selected.returncode == 0 and Path(selected_path).is_file():
                        checked_candidates.append(selected_path)
                        continue
                except Exception:
                    pass
            checked_candidates.append(found)

    conda = shutil.which("conda")
    if conda:
        conda_dir = Path(conda).parent
        for filename in ("python.exe", "python"):
            candidate = conda_dir / filename
            if candidate.exists():
                checked_candidates.append(str(candidate))

    for candidate in checked_candidates:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            continue
        version_output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0 and version_output.startswith("Python "):
            return candidate

    print("No usable Python found!")
    return None


def _detect_xelatex() -> Optional[str]:
    """Locate XeLaTeX using the installed runner's PATH/Windows fallback order."""
    found = shutil.which("xelatex")
    if found:
        return found

    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["where.exe", "xelatex"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[0]
        except Exception:
            pass

    candidates: List[Path] = []
    if RUNTIME_TEXLIVE:
        candidates.extend((
            Path(RUNTIME_TEXLIVE) / "texmfs" / "install" / "miktex" / "bin" / "x64" / "xelatex.exe",
            Path(RUNTIME_TEXLIVE) / "bin" / "windows" / "xelatex.exe",
            Path(RUNTIME_TEXLIVE) / "miktex" / "bin" / "x64" / "xelatex.exe",
        ))
    home = Path.home()
    candidates.extend((
        home / "AppData" / "Local" / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64" / "xelatex.exe",
        Path("C:/Program Files/MiKTeX/miktex/bin/x64/xelatex.exe"),
        Path("C:/MiKTeX/miktex/bin/x64/xelatex.exe"),
        Path("D:/MiKTeX/miktex/bin/x64/xelatex.exe"),
        Path("C:/texlive/2026/bin/windows/xelatex.exe"),
        Path("C:/texlive/2025/bin/windows/xelatex.exe"),
        Path("C:/texlive/2024/bin/windows/xelatex.exe"),
    ))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


_DETECTED_PYTHON = _detect_python()
_DETECTED_XELATEX = _detect_xelatex()


def _python_command_name() -> str:
    """Return a shell-safe bare command name for the detected Python interpreter.

    On Windows the full path resolves to ``python.exe``.  Passing that name to
    run_command triggers the allowlist security check ("command path must be a
    bare allowlisted program name") because the ``.exe`` suffix is treated as a
    path component.  Stripping the extension returns the allowlisted bare name
    ``python`` that the agent can actually use.
    """
    if not _DETECTED_PYTHON:
        return ""
    name = Path(_DETECTED_PYTHON).name or str(_DETECTED_PYTHON)
    # Strip .exe so the allowlist accepts "python" rather than rejecting "python.exe"
    if name.lower().endswith(".exe"):
        name = Path(name).stem
    return name

_EXECUTION_INSTRUCTIONS = """## IMPORTANT EXECUTION INSTRUCTIONS
You are running in non-interactive mode (claude -p). Do NOT use slash commands like /skill-name. Instead, directly execute the task described below. You MUST write output files to the current working directory. Use the tools available to you to complete the task.

## CRITICAL TOOL USAGE RULES
Every tool call MUST include all required parameters. Never send a tool call with empty input. For large files, write in sections so tool calls are not truncated.

## PYTHON ENVIRONMENT
The working Python interpreter is: {python_path}
Use this exact interpreter for Python scripts and package operations.

## ⛔ LARGE DATA FILE HANDLING (MANDATORY — context overflow kills the run)
Data files in user_data/ (CSV, Excel exports, TSV, or any file > 80 lines) contain
thousands of rows. Reading them raw with the read tool floods the context window and
causes immediate API failure (rc=1).

REQUIRED workflow for every data file:
1. Write a one-shot Python script to _tmp/ and run it (python -c is NOT allowed):
     write("_tmp/data_preview.py", content=\'\'\'
import pandas as pd
df = pd.read_csv("user_data/<actual_filename>.txt", sep="\\t", encoding="utf-8", on_bad_lines="skip")
print("shape:", df.shape)
print(df.dtypes.to_string())
print(df.describe(include="all").to_string())
print("missing:", df.isnull().sum().to_string())
print("head:"); print(df.head(3).to_string())
\'\'\')
     run_command("python", args=["_tmp/data_preview.py"])
2. Only the printed output goes into context — never the raw rows.
3. For per-column stats or subsets, add more print() calls to the same script.

⛔ Never call read() on a data file larger than 80 lines.
⛔ Never loop read() across data file line ranges — use Python instead.
⛔ Never use "python.exe" — always use the bare name "python".
⛔ Never use python -c (inline code) — always write to a .py file and run it.
✅ Use read() only for problem-statement PDFs, SKILL.md, _utils/ reference files,
   and output reports you have already written yourself.

## VERIFIED RESEARCH HELPERS
Shared support files are mounted at _utils/. Use $REVIEWER_SCRIPT for
independent review and $SCHOLAR_SCRIPT for literature lookup. These paths are
verified by the host before execution; do not replace them with invented or
best-effort substitutes.
"""


def _load_skill_prompt(skill_name: str, arguments: str, extra_params: Optional[Dict] = None) -> str:
    """Load SKILL.md, substitute arguments, and build the non-interactive prompt."""
    from services.skill_crypto import decrypt_skill_md

    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    content = decrypt_skill_md(SKILLS_DIR, skill_name)
    if content is None:
        return (
            f"Please execute the research task '{skill_name}' for the topic: {arguments}\n"
            f"Skill file not found: {skill_md}"
        )
    content = content.replace("$ARGUMENTS", arguments)
    prompt = _EXECUTION_INSTRUCTIONS.format(python_path=_python_command_name()).rstrip() + "\n\n" + content.rstrip()
    if extra_params:
        prompt += "\n\n## Additional Parameters\n"
        prompt += "\n".join(f"- {key}: {value}" for key, value in extra_params.items())
    return prompt


class ClaudeRunner:
    """Workflow-agent facade.

    New profiles execute through the in-process Responses tool loop.  The
    historical class name remains API-compatible; Claude Code is only invoked
    when a user explicitly selects a non-Responses executor and provides an
    external installation.
    """

    def __init__(self):
        self.claude_bin = CLAUDE_BIN
        self.skills_dir = SKILLS_DIR
        self.tools_dir = TOOLS_DIR
        # Workflow steps create fresh ClaudeRunner instances.  A shared
        # registry is therefore required for pause/delete to find every child.
        self._processes = _ACTIVE_CLAUDE_PROCESSES

    async def _run_mock_skill(
        self,
        *,
        skill_name: str,
        cwd: Path,
        workflow_id: str,
        on_output: Optional[Callable[[str], Awaitable[None]]] = None,
        resume_session_id: Optional[str] = None,
    ) -> Dict:
        """Deterministic skill execution for offline lifecycle tests."""
        cwd = Path(cwd)
        cwd.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", skill_name)
        marker = cwd / f"_mock_skill_{safe}.ok"
        marker.write_text(f"ok:{skill_name}:{workflow_id}\n", encoding="utf-8")
        ledger = cwd / "_mock_skill_calls.jsonl"
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "skill_name": skill_name,
                        "workflow_id": workflow_id,
                        "cwd": str(cwd),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        # Produce common primary outputs so engine checkpoint/primary checks pass.
        body = ("mock output for " + skill_name + "\n") * 40
        skill_artifacts: Dict[str, str] = {
            "research-lit": "literature_review.md",
            "idea-creator": "IDEA_REPORT.md",
            "novelty-check": "novelty_check_report.md",
            "research-review": "review_report.md",
            "paper-plan": "PAPER_PLAN.md",
            "paper-plan-zh": "PAPER_PLAN.md",
            "paper-analysis": "RESULTS.md",
            "paper-write": "paper/main.tex",
            "paper-write-zh": "paper/main.tex",
            "paper-compile": "paper/main.pdf",
            "paper-compile-zh": "paper/main.pdf",
            "grad-project": "README.md",
            "copyright-material": "software-copyright/PRODUCT_OVERVIEW.md",
            "patent-disclosure": "patent/INVENTION_DISCLOSURE.md",
            "invention-structuring": "patent/INVENTION_DISCLOSURE.md",
            "comp-prob-analysis": "PROBLEM_ANALYSIS.md",
            "comp-modeling": "MODELING.md",
            "comp-code": "code/main.py",
            "comp-paper-zh": "paper/main.tex",
            "comp-compile-zh": "paper/main.pdf",
            "comp-paper": "paper/main.tex",
            "comp-compile": "paper/main.pdf",
        }
        target_name = skill_artifacts.get(skill_name)
        if target_name:
            target = cwd / target_name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix.lower() == ".pdf":
                target.write_bytes(b"%PDF-1.4\n% mock\n")
            else:
                target.write_text(f"# {skill_name}\n\n{body}", encoding="utf-8")
        # Always leave a figures placeholder for figure-oriented steps.
        if "figure" in skill_name or skill_name in {"experiment-bridge", "nature-figure"}:
            figures = cwd / "figures"
            figures.mkdir(parents=True, exist_ok=True)
            (figures / "latex_includes.tex").write_text("% mock figures\n", encoding="utf-8")
            (figures / "experiment_data.json").write_text("{}", encoding="utf-8")
        if skill_name in {"research-refine-pipeline", "research-refine"}:
            refine = cwd / "refine-logs"
            refine.mkdir(parents=True, exist_ok=True)
            (refine / "FINAL_PROPOSAL.md").write_text(f"# proposal\n{body}", encoding="utf-8")
            (refine / "EXPERIMENT_PLAN.md").write_text(f"# plan\n{body}", encoding="utf-8")
        if "copyright" in skill_name or skill_name.startswith("software"):
            soft = cwd / "software-copyright"
            soft.mkdir(parents=True, exist_ok=True)
            # software_copyright host inventory four-pack (distinct from copyright_material form pack)
            for name in (
                "PRODUCT_OVERVIEW.md",
                "USER_MANUAL.md",
                "SOURCE_CODE_INDEX.md",
                "REGISTRATION_CHECKLIST.md",
            ):
                (soft / name).write_text(f"# {name}\n{body}", encoding="utf-8")
            form_pack = cwd / "软件著作权申请资料" / "草稿"
            form_pack.mkdir(parents=True, exist_ok=True)
            (form_pack / "申请表信息.md").write_text(f"# form\n{body}", encoding="utf-8")
        if "patent" in skill_name or skill_name in {"invention-structuring", "claims-drafting"}:
            patent = cwd / "patent"
            patent.mkdir(parents=True, exist_ok=True)
            (patent / "INVENTION_DISCLOSURE.md").write_text(f"# disclosure\n{body}", encoding="utf-8")

        line = f"[mock-agent] completed skill={skill_name}"
        if on_output is not None:
            try:
                await on_output(line)
            except Exception:
                log.debug("mock on_output failed", exc_info=True)
        # Brief yield so concurrent pause/status polls observe running state.
        await asyncio.sleep(0.05)
        return {
            "success": True,
            "stdout": line,
            "stderr": "",
            "returncode": 0,
            "return_code": 0,
            "result": line,
            "session_id": resume_session_id or "mock-session",
        }

    async def run_skill(
        self,
        skill_name: str,
        arguments: str,
        cwd: Union[str, Path],
        workflow_id: str,
        on_output: Optional[Callable[[str], Awaitable[None]]] = None,
        extra_params: Optional[Dict] = None,
        workspace_files: Optional[List[str]] = None,
        context_summary: Optional[str] = None,
        inactivity_timeout: int = 2400,
        overall_timeout: int = 7200,
        resume_session_id: Optional[str] = None,
    ) -> Dict:
        """通过默认 Responses agent 或可选外部 Claude 执行一个 skill。

        Args:
            skill_name: skill 名称 (例如 'paper-write')
            arguments: 传给 skill 的参数字符串
            cwd: 工作目录
            workflow_id: 工作流 ID
            on_output: 输出回调函数
            extra_params: 额外参数
            workspace_files: 工作区文件列表
            context_summary: 上下文摘要
            inactivity_timeout: 无活动超时(秒)
            overall_timeout: 总超时(秒)

        Returns:
            {"success": bool, "stdout": str, "stderr": str, "returncode": int}
        """
        prompt = _load_skill_prompt(skill_name, arguments, extra_params)
        if workspace_files:
            prompt += "\n\n## Existing Workspace Files\n" + "\n".join(f"- {path}" for path in workspace_files)
        if context_summary:
            prompt += "\n\n## Existing Workspace Context\n" + context_summary

        # Honest offline agent path used by lifecycle/parity tests. Still runs
        # through ClaudeRunner.run_skill and the real workflow engine; only the
        # external LLM/CLI transport is replaced with deterministic artifacts.
        if str(os.environ.get("VIBE_MOCK_AGENT", "")).strip().lower() in {"1", "true", "yes", "on"}:
            return await self._run_mock_skill(
                skill_name=skill_name,
                cwd=Path(cwd),
                workflow_id=workflow_id,
                on_output=on_output,
                resume_session_id=resume_session_id,
            )

        try:
            runtime_contract = _prepare_skill_runtime(cwd)
        except RuntimeError as exc:
            message = str(exc)
            log.error("Skill runtime preflight failed for %s: %s", skill_name, message)
            return {
                "success": False,
                "stdout": "",
                "stderr": message,
                "returncode": -1,
                "result": "",
                "session_id": resume_session_id,
            }
        skill_parameter_env = _skill_parameter_environment(extra_params)

        # Responses is not an Anthropic Messages transport.  Execute it with
        # an explicit local tool loop rather than passing its credentials to
        # Claude Code and hoping the wire protocols happen to match.
        from services.llm_client import get_all_settings

        try:
            settings = await get_all_settings()
        except Exception as exc:
            log.warning("Executor settings unavailable: %s", exc)
            settings = {}
        executor_provider = (
            str(settings.get("executor_provider", "openai_responses")).strip()
            or "openai_responses"
        )
        if executor_provider in {"openai_responses", "openai_compatible"}:
            from services.llm_client import (
                _configured_agent,
                _request_parameters,
                get_env_for_subprocess,
            )
            from services.openai_responses_agent import (
                OpenAICompatibleAgent,
                OpenAIResponsesAgent,
            )

            try:
                _, base_url, api_key, model_id = _configured_agent(settings, "executor")
                parameters = _request_parameters(settings, "executor", default_max_tokens=8192)
                mounted_skill = _mount_skill_support(skill_name, cwd)
            except Exception as exc:
                message = str(exc)
                if settings.get("executor_api_key"):
                    message = message.replace(str(settings["executor_api_key"]), "[redacted]")
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": message,
                    "returncode": -1,
                    "result": "",
                    "session_id": resume_session_id,
                }

            agent_env = _minimal_agent_environment(dict(os.environ))
            agent_env.update(_minimal_agent_environment(await get_env_for_subprocess()))
            # The credential belongs to the in-process transport, not to
            # commands chosen by the model. Reviewer/editor helper credentials
            # remain available under their own role-specific variables.
            agent_env.pop("ANTHROPIC_API_KEY", None)
            agent_env.pop("ANTHROPIC_BASE_URL", None)
            _augment_runtime_path(agent_env)
            agent_env.update(runtime_contract)
            agent_env.update(skill_parameter_env)
            agent_env["WORKFLOW_ID"] = workflow_id
            if mounted_skill is not None:
                agent_env["CLAUDE_SKILL_DIR"] = str(mounted_skill)
                transport_label = (
                    "Responses" if executor_provider == "openai_responses" else "Chat Completions"
                )
                prompt += (
                    f"\n\n## Local {transport_label} Tool Mapping\n"
                    "Use read/write/replace/list/search/mkdir/run_command to carry out this skill. "
                    "Paths for file tools must stay inside the workflow workspace. "
                    f"The skill support directory (formerly $CLAUDE_SKILL_DIR) is "
                    f"{mounted_skill.relative_to(Path(cwd).resolve()).as_posix()}. "
                    "Sibling skill dependencies and shared-references are mounted beside it. "
                    "Use run_command with shell=true only when a pipeline or shell conditional is required."
                )
            agent_cls = (
                OpenAIResponsesAgent
                if executor_provider == "openai_responses"
                else OpenAICompatibleAgent
            )
            agent = agent_cls(
                base_url=base_url,
                api_key=api_key,
                model_id=model_id,
                parameters=parameters,
                environment=agent_env,
            )
            registry_key = _register_active_execution(
                _ACTIVE_RESPONSES_AGENTS, workflow_id, agent
            )
            try:
                return await agent.run(
                    prompt=prompt,
                    cwd=cwd,
                    workflow_id=workflow_id,
                    on_output=on_output,
                    inactivity_timeout=inactivity_timeout,
                    overall_timeout=overall_timeout,
                    resume_session_id=resume_session_id,
                )
            except asyncio.CancelledError:
                await agent.cancel()
                raise
            finally:
                _unregister_active_execution(
                    _ACTIVE_RESPONSES_AGENTS, registry_key, agent
                )

        cmd = [
            self.claude_bin,
            "-p",
            "--bare",
            "--setting-sources",
            "project,local",
            "--verbose",
            "--output-format",
            "stream-json",
        ]
        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])
        env = _minimal_agent_environment(dict(os.environ))
        from services.llm_client import get_env_for_subprocess
        env.update(_minimal_agent_environment(await get_env_for_subprocess()))
        configured_claude_bin = env.get("CLAUDE_BIN", "").strip()
        # An instance-level override is useful for diagnostics/tests. Normal
        # instances retain the config default and should follow the persisted
        # setting exposed through CLAUDE_BIN.
        if configured_claude_bin and self.claude_bin == CLAUDE_BIN:
            cmd[0] = configured_claude_bin
        _augment_runtime_path(env)
        env.update(runtime_contract)
        env.update(skill_parameter_env)
        executor_model = env.get("EXECUTOR_MODEL_ID", "").strip()
        if executor_model:
            cmd.extend(["--model", executor_model])
        env["CLAUDE_SKILL_DIR"] = str(self.skills_dir / skill_name) if (self.skills_dir / skill_name).exists() else ""
        env["WORKFLOW_ID"] = workflow_id

        proc: Optional[asyncio.subprocess.Process] = None
        process_registry_key: Optional[str] = None
        tasks: List[asyncio.Task] = []
        proc_wait_task: Optional[asyncio.Task] = None
        try:
            process_group_options: Dict[str, Any] = {}
            if os.name == "nt":
                # CREATE_NO_WINDOW changes cmd.exe's code-page behavior and
                # breaks UTF-8 batch shims whose executable path is non-ASCII.
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                if Path(cmd[0]).suffix.lower() not in {".cmd", ".bat"}:
                    flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process_group_options["creationflags"] = flags
            else:
                process_group_options["start_new_session"] = True
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
                **process_group_options,
            )
            process_registry_key = _register_active_execution(
                self._processes, workflow_id, proc
            )
            if proc.stdin is not None:
                proc.stdin.write(prompt.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()

            stdout_lines = []
            stderr_lines = []
            result_text = ""
            session_id = resume_session_id
            last_activity = asyncio.get_event_loop().time()
            start_time = last_activity

            async def read_stream(stream, lines, is_stderr=False):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    lines.append(decoded)
                    if not is_stderr:
                        display = decoded
                        try:
                            event = json.loads(decoded)
                        except json.JSONDecodeError:
                            event = None
                        if isinstance(event, dict):
                            nonlocal result_text, session_id
                            session_id = event.get("session_id") or session_id
                            if isinstance(event.get("result"), str):
                                result_text = event["result"]
                            elif isinstance(event.get("text"), str):
                                display = event["text"]
                            elif isinstance(event.get("message"), dict):
                                content = event["message"].get("content")
                                if isinstance(content, str):
                                    display = content
                        if on_output and display:
                            await on_output(display)
                    nonlocal last_activity
                    last_activity = asyncio.get_event_loop().time()

            tasks = [
                asyncio.create_task(read_stream(proc.stdout, stdout_lines)),
                asyncio.create_task(read_stream(proc.stderr, stderr_lines, is_stderr=True)),
            ]

            proc_wait_task = asyncio.create_task(proc.wait())
            timeout_reason = None
            while not proc_wait_task.done():
                await asyncio.sleep(0.25)
                now = asyncio.get_event_loop().time()
                if now - start_time >= overall_timeout:
                    timeout_reason = f"Claude process exceeded overall timeout ({overall_timeout}s)"
                    break
                if now - last_activity >= inactivity_timeout:
                    timeout_reason = f"Claude process produced no output for {inactivity_timeout}s"
                    break

            if timeout_reason and proc.returncode is None:
                await self._kill_process_tree(proc)

            if timeout_reason:
                pending = [proc_wait_task, *tasks]
                for task in pending:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            else:
                if not proc_wait_task.done():
                    await proc_wait_task
                await asyncio.gather(*tasks, return_exceptions=True)

            if timeout_reason:
                stderr_lines.append(timeout_reason)

            return {
                "success": timeout_reason is None and proc.returncode == 0,
                "stdout": "\n".join(stdout_lines),
                "stderr": "\n".join(stderr_lines),
                "returncode": proc.returncode if proc.returncode is not None else -1,
                "result": result_text,
                "session_id": session_id,
            }
        except asyncio.CancelledError:
            if proc is not None and proc.returncode is None:
                await self._kill_process_tree(proc)
            pending = ([proc_wait_task] if proc_wait_task is not None else []) + tasks
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise
        except FileNotFoundError:
            log.error("Claude binary not found: %s", cmd[0])
            return {"success": False, "stdout": "", "stderr": f"Claude binary not found: {cmd[0]}", "returncode": -1, "result": "", "session_id": resume_session_id}
        except Exception as e:
            if proc is not None and proc.returncode is None:
                await self._kill_process_tree(proc)
            pending = ([proc_wait_task] if proc_wait_task is not None else []) + tasks
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            log.error("Claude runner error: %s", e)
            return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1, "result": "", "session_id": resume_session_id}
        finally:
            if proc is not None and process_registry_key is not None:
                _unregister_active_execution(
                    self._processes, process_registry_key, proc
                )

    async def cancel(self, workflow_id_prefix: str) -> bool:
        """Cancel every tracked subprocess whose workflow id matches the prefix."""
        with _ACTIVE_EXECUTIONS_LOCK:
            matches = [
                (key, proc)
                for key, proc in self._processes.items()
                if key.startswith(workflow_id_prefix)
            ]
            agent_matches = [
                (key, agent)
                for key, agent in _ACTIVE_RESPONSES_AGENTS.items()
                if key.startswith(workflow_id_prefix)
            ]
        outcomes = await asyncio.gather(
            *(self._kill_process_tree(proc) for _, proc in matches),
            *(agent.cancel() for _, agent in agent_matches),
            return_exceptions=True,
        )
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                log.error("Execution cancellation cleanup failed: %s", outcome)
        return bool(matches or agent_matches)

    async def _kill_process_tree(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        if os.name == "nt" and proc.pid:
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                tree_kill_failed = result.returncode != 0
            except OSError as exc:
                log.warning("taskkill failed for subprocess %s: %s", proc.pid, exc)
                tree_kill_failed = True
            if tree_kill_failed and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        elif proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            # Never let a failed tree-kill turn workflow cancellation into an
            # unbounded wait.  Killing the root is the final portable fallback.
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                log.error("Subprocess %s did not exit after forced termination", proc.pid)

    def is_running(self, workflow_id: str) -> bool:
        with _ACTIVE_EXECUTIONS_LOCK:
            agents = [
                agent
                for key, agent in _ACTIVE_RESPONSES_AGENTS.items()
                if key == workflow_id or key.startswith(f"{workflow_id}#")
            ]
            processes = [
                proc
                for key, proc in self._processes.items()
                if key == workflow_id or key.startswith(f"{workflow_id}#")
            ]
        return any(bool(agent.is_running) for agent in agents) or any(
            proc.returncode is None for proc in processes
        )


async def cancel_workflow_execution(workflow_id_prefix: str) -> bool:
    """Cancel CLI process trees and Responses loops across runner instances.

    Workflow routes can call this before or immediately after cancelling the
    orchestration task.  Step registry keys begin with the workflow id, so one
    prefix cancels normal, retry, recovery, and checkpoint-revision runs.
    """
    if not workflow_id_prefix:
        return False
    return await ClaudeRunner().cancel(workflow_id_prefix)
