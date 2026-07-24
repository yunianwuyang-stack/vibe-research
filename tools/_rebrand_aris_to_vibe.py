"""One-shot brand rebrand: ARIS harness tokens -> Vibe Research."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent if False else Path(".")
TARGETS = [
    ROOT / "skills",
    ROOT / "backend" / "config.py",
    ROOT / "desktop-data.js",
]
SUFFIXES = {".md", ".py", ".js", ".sh", ".ps1", ".json", ".txt", ".yml", ".yaml"}

# Ordered replacements (specific before generic).
REPLACEMENTS: list[tuple[str, str]] = [
    ("ARIS_REPO", "VIBE_REPO"),
    ("ARIS_CONDA_HOOK", "VIBE_CONDA_HOOK"),
    ("install_aris_codex.sh", "install_vibe_codex.sh"),
    ("install_aris.sh", "install_vibe.sh"),
    ("aris-research-suite", "vibe-research-suite"),
    ("aris-research", "vibe-research"),
    (".aris/", ".vibe/"),
    (".aris\\", ".vibe\\"),
    ("`.aris`", "`.vibe`"),
    ("/.aris", "/.vibe"),
    (" paper/.aris", " paper/.vibe"),
    ("ARIS Meta-Optimization", "Vibe Research Meta-Optimization"),
    ("Outer-Loop Harness Optimization for ARIS", "Outer-Loop Harness Optimization for Vibe Research"),
    ("for ARIS", "for Vibe Research"),
    ("of ARIS", "of Vibe Research"),
    ("to ARIS", "to Vibe Research"),
    ("in ARIS", "in Vibe Research"),
    ("an ARIS", "a Vibe Research"),
    ("the ARIS", "the Vibe Research"),
    ("using ARIS", "using Vibe Research"),
    ("Analyze ARIS", "Analyze Vibe Research"),
    ("ARIS usage", "Vibe Research usage"),
    ("ARIS is a", "Vibe Research is a"),
    ("ARIS has", "Vibe Research has"),
    ("ARIS tech", "Vibe Research tech"),
    ("ARIS's", "Vibe Research's"),
    ("ARIS’", "Vibe Research’s"),
    ("ARIS Markdown", "Vibe Research Markdown"),
    ("ARIS audit", "Vibe Research audit"),
    ("ARIS SKILL", "Vibe Research SKILL"),
    ("# ARIS", "# Vibe Research"),
    ("**ARIS**", "**Vibe Research**"),
    ("`ARIS`", "`Vibe Research`"),
    (" ARIS ", " Vibe Research "),
    (" ARIS.", " Vibe Research."),
    (" ARIS,", " Vibe Research,"),
    (" ARIS:", " Vibe Research:"),
    (" ARIS)", " Vibe Research)"),
    ("(ARIS ", "(Vibe Research "),
    ("(ARIS)", "(Vibe Research)"),
    ("\"ARIS\"", "\"Vibe Research\""),
    ("'ARIS'", "'Vibe Research'"),
]

# Remaining bare ARIS tokens (word boundary), after ordered replacements.
BARE_ARIS = re.compile(r"\bARIS\b")

changed = []
scanned = 0
for target in TARGETS:
    files = []
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = [p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES]
    for path in files:
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        original = text
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        # Case-sensitive bare leftover
        text = BARE_ARIS.sub("Vibe Research", text)
        # Lowercase path leftovers like 'aris/' only when clearly brand dirs
        text = text.replace("install_aris", "install_vibe")
        if text != original:
            path.write_text(text, encoding="utf-8", newline="\n")
            changed.append(path.as_posix())

print(f"scanned={scanned} changed={len(changed)}")
for p in changed:
    print(p)

# Residual check in skills/backend/desktop-data (allow aris.db migration only)
allow_aris_db = True
residual = []
pat = re.compile(r"ARIS_REPO|install_aris|\.aris\b|aris-research|\bARIS\b", re.I)
for target in TARGETS:
    files = [target] if target.is_file() else [p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in SUFFIXES]
    for path in files:
        try:
            t = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # strip allowed legacy db filename mentions for residual report
        t2 = t.replace("aris.db", "LEGACY_DB")
        if pat.search(t2):
            residual.append(path.as_posix())
print("residual_after", len(residual))
for p in residual[:30]:
    print(" residual", p)
