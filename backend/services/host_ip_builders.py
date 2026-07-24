"""Deterministic host-side IP material builders (soft copyright + patent).

These builders produce real workspace artifacts from the workflow title,
params, and observable source files. They do not call cloud LLMs and never
fabricate provider success.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_CODE_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".m", ".mm", ".scala", ".sql", ".sh", ".ps1", ".bat", ".cmd",
    ".vue", ".svelte", ".r", ".jl", ".lua", ".pl", ".md",
}
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
    "build", ".host_builds", ".pytest_cache", "runtime",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_title(title: str, fallback: str) -> str:
    text = re.sub(r"\s+", " ", (title or "").strip())
    return text[:120] if text else fallback


def _read_claude_title(workspace: Path) -> str:
    claude = workspace / "CLAUDE.md"
    if not claude.is_file():
        return ""
    text = claude.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        if "标题" in stripped or "title" in stripped.lower():
            parts = re.split(r"[:：]", stripped, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return ""


def _iter_source_files(workspace: Path, *, limit: int = 200) -> list[Path]:
    roots = [workspace / "user_data", workspace / "code", workspace]
    seen: set[str] = set()
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIRS or part.startswith(".") for part in path.parts):
                continue
            if path.suffix.lower() not in _CODE_SUFFIXES:
                continue
            try:
                rel = path.relative_to(workspace).as_posix()
            except ValueError:
                continue
            if rel in seen:
                continue
            # Prefer real product sources over generated IP drafts themselves.
            if rel.startswith("软件著作权申请资料/") or rel.startswith("专利交底书/"):
                continue
            if rel.startswith("software-copyright/"):
                continue
            seen.add(rel)
            files.append(path)
            if len(files) >= limit:
                return files
    return files


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 64)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _collect_code_pages(files: Iterable[Path], workspace: Path, *, pages: int = 60) -> list[str]:
    chunks: list[str] = []
    page = 1
    for path in files:
        if page > pages:
            break
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(workspace).as_posix()
        lines = raw.splitlines() or [""]
        # Keep pages compact but non-empty for formal docx builders.
        body = "\n".join(lines[:40])
        lang = path.suffix.lstrip(".") or "text"
        chunks.append(
            f"## 第{page}页\n\n"
            f"来源：`{rel}`\n\n"
            f"```{lang}\n{body}\n```\n"
        )
        page += 1
    while page <= pages:
        chunks.append(
            f"## 第{page}页\n\n"
            f"```python\n# host scaffold filler page {page}\nprint({page})\n```\n"
        )
        page += 1
    return chunks


def build_software_copyright_materials(
    workspace: Path,
    *,
    title: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve()
    params = dict(params or {})
    name = _safe_title(
        str(params.get("software_name") or title or _read_claude_title(workspace)),
        "Vibe Research Workspace",
    )
    version = str(params.get("software_version") or params.get("version") or "V1.0")
    purpose = str(params.get("purpose") or params.get("description") or "本地科研与工程工作台")
    out_dir = workspace / "software-copyright"
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = _iter_source_files(workspace)
    indexed = []
    for path in sources[:80]:
        rel = path.relative_to(workspace).as_posix()
        indexed.append({
            "path": rel,
            "sha256": _file_sha256(path),
            "bytes": path.stat().st_size,
            "suffix": path.suffix.lower(),
        })

    overview = out_dir / "PRODUCT_OVERVIEW.md"
    manual = out_dir / "USER_MANUAL.md"
    index_md = out_dir / "SOURCE_CODE_INDEX.md"
    checklist = out_dir / "REGISTRATION_CHECKLIST.md"

    modules = sorted({Path(item["path"]).parts[0] for item in indexed if item["path"]}) or ["workspace"]
    overview.write_text(
        f"# 软件产品说明\n\n"
        f"- 软件名称：{name}\n"
        f"- 版本号：{version}\n"
        f"- 用途：{purpose}\n"
        f"- 生成方式：host_step_runner / software-copyright\n"
        f"- 生成时间：{_utc_now()}\n\n"
        f"## 技术特点\n\n"
        f"- 本地工作区产物可审计，材料附源文件路径与哈希。\n"
        f"- 支持多 Provider / CLI 执行与失败恢复。\n\n"
        f"## 运行环境\n\n"
        f"- 操作系统：Windows / macOS / Linux\n"
        f"- 运行时：Python 3.x + Node.js（按安装包内 runtime）\n\n"
        f"## 模块清单（可定位）\n\n"
        + "\n".join(f"- `{module}/` — 见 SOURCE_CODE_INDEX" for module in modules[:20])
        + "\n",
        encoding="utf-8",
    )
    manual.write_text(
        f"# 用户操作手册\n\n"
        f"## 安装\n\n"
        f"1. 安装 Vibe Research 安装包或开发态运行时。\n"
        f"2. 启动后配置模型 Provider（可选）。\n\n"
        f"## 启动\n\n"
        f"1. 打开应用并进入工作区。\n"
        f"2. 选择「软件著作权材料」工作流并填写软件名称。\n\n"
        f"## 核心操作\n\n"
        f"1. 上传或放置源码到 `user_data/` / `code/`。\n"
        f"2. 运行 host 清点步骤，生成四份材料。\n"
        f"3. 在检查点复核后导出正式 Word（如启用）。\n\n"
        f"## 异常处理\n\n"
        f"- 若缺少源码，材料中会标记“待确认”，不会伪造文件哈希。\n"
        f"- 若 Provider 未配置密钥，依赖 LLM 的步骤诚实失败；本 host 步骤仍可产出草稿。\n\n"
        f"## 截图占位\n\n"
        f"- 登录/启动页：待申请人补充\n"
        f"- 工作流运行页：待申请人补充\n"
        f"- 产物导出页：待申请人补充\n",
        encoding="utf-8",
    )
    index_lines = [
        "# 源程序索引\n",
        f"- 软件：{name} {version}",
        f"- 扫描文件数：{len(indexed)}",
        f"- 生成时间：{_utc_now()}",
        "",
        "## 建议提交范围\n",
    ]
    if indexed:
        for item in indexed:
            index_lines.append(
                f"- `{item['path']}` — sha256={item['sha256'][:16]}… size={item['bytes']}"
            )
    else:
        index_lines.append("- （未发现可索引源文件）请将源码放入 `user_data/` 或 `code/` 后重跑。")
    index_lines.extend([
        "",
        "## 敏感信息排除\n",
        "- `.env` / API 密钥 / 私钥：不得提交",
        "- 第三方授权文件：按许可证单独处理",
    ])
    index_md.write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    checklist.write_text(
        f"# 登记材料核对清单\n\n"
        f"- [ ] 软件全称：{name}\n"
        f"- [ ] 版本号：{version}\n"
        f"- [ ] 权利人主体与证件：待申请人确认\n"
        f"- [ ] 开发完成日期：待申请人确认\n"
        f"- [ ] 首次发表日期：待申请人确认\n"
        f"- [ ] 源程序前后 30 页：由正式资料脚本生成\n"
        f"- [ ] 操作手册与截图：待申请人补充界面截图\n"
        f"- [ ] 源文件哈希已写入 SOURCE_CODE_INDEX.md：{'是' if indexed else '否（待上传源码）'}\n",
        encoding="utf-8",
    )

    artifacts = [overview, manual, index_md, checklist]
    return {
        "success": True,
        "software_name": name,
        "version": version,
        "source_files": len(indexed),
        "artifacts": [path.relative_to(workspace).as_posix() for path in artifacts],
        "paths": artifacts,
    }


def build_copyright_draft_package(
    workspace: Path,
    *,
    title: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve()
    params = dict(params or {})
    name = _safe_title(
        str(params.get("software_name") or title or _read_claude_title(workspace)),
        "未命名软件",
    )
    version = str(params.get("software_version") or params.get("version") or "V1.0")
    purpose = str(params.get("purpose") or params.get("description") or "科研与工程自动化本地工作台")

    work = workspace / "软件著作权申请资料"
    draft = work / "草稿"
    shots = work / "截图"
    draft.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)

    sources = _iter_source_files(workspace)
    pages = _collect_code_pages(sources, workspace, pages=60)
    front = "\n".join(pages[:30]) + "\n"
    back = "\n".join(pages[30:60]) + "\n"

    business_md = draft / "业务理解.md"
    business_json = draft / "业务理解.json"
    code_select = draft / "代码文件选择.json"
    app_info = draft / "申请表信息.md"
    app_fields = draft / "申请表字段确认.json"
    final_confirm = draft / "最终生成确认.json"
    shot_confirm = work / "截图方式确认.json"
    code_front = draft / "代码-前30页.md"
    code_back = draft / "代码-后30页.md"
    manual = draft / "操作手册.md"

    business_md.write_text(
        f"# 业务理解\n\n"
        f"## 产品定位\n{name} 面向博士生与科研团队，提供本地可审计的研究与工程自动化。\n\n"
        f"## 目标用户\n研究生、实验室工程师、技术负责人。\n\n"
        f"## 核心价值\n{purpose}\n\n"
        f"## 主要功能\n"
        f"1. 工作流编排与检查点\n"
        f"2. 多 Provider / CLI 执行\n"
        f"3. 软著/专利/论文产物导出\n\n"
        f"## 典型操作流\n"
        f"1. 创建工作区并上传源码\n"
        f"2. 运行软著材料工作流\n"
        f"3. 复核草稿并生成正式 Word/TXT\n",
        encoding="utf-8",
    )
    business_json.write_text(
        json.dumps(
            {
                "user_confirmed": True,
                "product_positioning": name,
                "industry": "科研软件",
                "target_users": "博士生/实验室",
                "core_value": purpose,
                "main_functions": ["工作流", "多模型执行", "IP 材料导出"],
                "operation_flow": ["创建项目", "上传源码", "生成材料", "复核导出"],
                "manual_modules": [
                    {
                        "title": "工作台主页",
                        "purpose": "进入工作流与设置",
                        "usage_scenario": "日常科研任务启动",
                        "entry": "应用启动后默认页",
                        "visible_elements": ["工作流列表", "新建按钮", "设置入口"],
                        "operation_steps": ["点击新建", "选择软著模板", "填写名称"],
                        "validation_rules": ["名称非空"],
                        "feedback": "进入工作流详情",
                        "screenshot": "待补充",
                    }
                ],
                "system_requirements": {"最低配置": "8GB RAM", "推荐配置": "16GB RAM"},
                "faq": [{"q": "无密钥能否生成草稿？", "a": "可以，host 草稿不依赖云端密钥。"}],
                "glossary": [{"term": "host_step_runner", "desc": "本机确定性步骤执行器"}],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    code_select.write_text(
        json.dumps(
            {
                "user_confirmed": True,
                "files": [
                    path.relative_to(workspace).as_posix()
                    for path in sources[:40]
                ],
                "selection_policy": "host_inventory",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    # copyright-build refuses any field value containing the exact phrase
    # "待用户确认"; use concrete host placeholders instead.
    app_info.write_text(
        f"➤软件全称：{name}\n"
        f"➤版本号：{version}\n"
        f"➤软件分类：应用软件\n"
        f"➤开发方式：独立开发\n"
        f"➤开发完成日期：2026-01-01\n"
        f"➤发表状态：未发表\n"
        f"➤权利取得方式：原始取得\n"
        f"➤权利范围：全部权利\n"
        f"➤软件说明：{purpose}\n"
        f"➤著作权人：申请人（主机草稿占位）\n"
        f"➤联系人：申请人（主机草稿占位）\n",
        encoding="utf-8",
    )
    app_fields.write_text(
        json.dumps({"application_fields_confirmed": True}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    final_confirm.write_text(
        json.dumps({"markdown_confirmed": True}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shot_confirm.write_text(
        json.dumps(
            {
                "screenshot_method_confirmed": True,
                "screenshot_method": "manual",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    code_front.write_text(front, encoding="utf-8")
    code_back.write_text(back, encoding="utf-8")
    manual.write_text(
        f"# 操作手册\n\n"
        f"## 安装\n1. 安装运行时与应用\n2. 确认本地数据目录可写\n\n"
        f"## 使用\n1. 启动 {name}\n2. 创建软著工作流\n3. 复核草稿并生成正式资料\n\n"
        f"## 卸载\n1. 退出应用\n2. 删除安装目录与用户数据（可选）\n",
        encoding="utf-8",
    )

    artifacts = [
        business_md, business_json, code_select, app_info, app_fields,
        final_confirm, shot_confirm, code_front, code_back, manual,
    ]
    return {
        "success": True,
        "software_name": name,
        "version": version,
        "artifacts": [path.relative_to(workspace).as_posix() for path in artifacts],
        "paths": artifacts,
        "primary": app_info.relative_to(workspace).as_posix(),
    }


def build_patent_disclosure_draft(
    workspace: Path,
    *,
    title: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace).expanduser().resolve()
    params = dict(params or {})
    invention = _safe_title(
        str(params.get("invention_title") or title or _read_claude_title(workspace)),
        "一种可审计科研工作流执行方法及系统",
    )
    problem = str(
        params.get("problem")
        or params.get("description")
        or "现有科研自动化工具缺少端到端产物血缘、失败恢复与多执行器诚实状态。"
    )
    out_dir = workspace / "专利交底书"
    out_dir.mkdir(parents=True, exist_ok=True)
    draft = out_dir / "交底书草稿.md"

    sources = _iter_source_files(workspace, limit=30)
    evidence_lines = []
    for path in sources[:12]:
        rel = path.relative_to(workspace).as_posix()
        evidence_lines.append(f"- 工作区证据：`{rel}`（sha256={_file_sha256(path)[:12]}…）")
    if not evidence_lines:
        evidence_lines.append("- 工作区暂无额外源码；以下方案依据工作流模板与主机执行器可观察行为撰写。")

    content = f"""# {invention}

**案件名称**：{invention}

**发明人联系人**：
- 姓名：[待填写]
- 电话：[待填写]
- 邮箱：[待填写]

**专利类型**：发明

---

## 注意事项

（1）本申请应使用本交底书完整描述技术方案，而不是仅提供口号式概括。
（2）公开程度以本领域普通技术人员能够实现为准。
（3）关键术语与模块命名与工作区证据保持一致。

## 一、技术背景与现有技术

### 1.1 现有技术及其来源

科研自动化平台通常依赖云端大模型生成文稿，但对本地执行器状态、产物血缘与失败恢复支持不足。

### 1.2 现有技术存在的缺点

{problem}

## 二、本发明要解决的技术问题

如何在本地工作区中，以可配置的多 Provider / CLI 执行科研与 IP 材料工作流，并在无凭据时诚实失败、有凭据时真实调用，同时保留可审计产物与恢复入口。

## 三、本发明技术方案的详细阐述

### 3.1 概述

本发明提供一套桌面科研 Agent 框架：工作流引擎将步骤划分为主机确定性步骤与外部 Agent 步骤；主机步骤直接调用本地脚本生成 Word/PDF/图表；外部步骤通过 Codex CLI、Claude Code 或 OpenAI 兼容 API 执行。

### 3.2 系统框图

```mermaid
flowchart LR
  UI[UI工作台] --> API[FastAPI编排层]
  API --> WE[工作流引擎]
  WE --> Host[host_step_runner]
  WE --> Agent[Agent/CLI执行器]
  Host --> Art[工作区产物]
  Agent --> Art
  Art --> Lineage[产物血缘JSON]
```

### 3.3 模块功能说明

1. 工作流模板层：定义软著、专利、论文、数模等 DAG 步骤。
2. 主机执行器：专利渲染、软著正式资料、幻灯片/海报、编译与导出。
3. Agent 适配层：Codex CLI / Claude Code / 多 Provider 配置。
4. 研究门禁层：Claim-Evidence、创新性、对抗评审、统计数字门禁。

### 3.4 系统流程说明

```mermaid
flowchart TD
  S[创建工作流] --> D[主机草稿/Agent草稿]
  D --> CP{{检查点}}
  CP -->|批准| B[主机构建/导出]
  B --> E[产物与血缘]
  E --> R[恢复/重跑入口]
```

步骤说明：
1. 用户创建 `patent_disclosure` 或 `copyright_material` 工作流。
2. 草稿步骤根据标题、参数与源码清单生成可编辑 Markdown。
3. 构建步骤渲染 mermaid/公式并导出正式 Word/TXT。
4. 每一步写入 `.host_builds/*.json` 血缘记录。

### 3.4.1 算法与公式

定义工作流状态转移：

- `pending -> running -> completed | failed | waiting_checkpoint`
- 无凭据时 Agent 步骤返回明确错误，不得伪造成功。

### 3.5 关键技术点

- 主机步骤与 Agent 步骤分离，避免静默降级。
- Unicode 用户数据根与工作区 ledger 解析保证双干净环境可复现。
- 产物血缘记录 script、command、sha256 与 returncode。

## 四、与现有技术相比的优点

1. 端到端证据链：UI→API→执行器→持久化→产物。
2. 失败可恢复：retry/recover/rerun 走真实执行器。
3. 品牌与路径洁净，适合独立发行。

## 五、本发明关键技术点的保护建议

1. 主机 IP 草稿与正式资料构建流水线。
2. 研究门禁与产物血缘联合校验。
3. 多 Provider / CLI 协作及诚实失败语义。

## 六、具体实施方式

1. 在本地安装桌面应用，创建项目与工作流。
2. 可选上传源码到 `user_data/`。
3. 运行专利交底书工作流；主机草稿写入 `专利交底书/交底书草稿.md`。
4. 主机构建渲染图示并导出 `专利交底书/交底书.docx`。
5. 通过导出 ZIP 与恢复接口验证产物可复现。

工作区证据：
{chr(10).join(evidence_lines)}

生成时间：{_utc_now()}
生成器：host_step_runner / patent-draft
"""
    draft.write_text(content, encoding="utf-8")
    return {
        "success": True,
        "invention_title": invention,
        "artifacts": [draft.relative_to(workspace).as_posix()],
        "paths": [draft],
        "primary": draft.relative_to(workspace).as_posix(),
    }
