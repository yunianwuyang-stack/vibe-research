import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Competitor / reverse-engineering brand tokens that must never ship in product
# surfaces. The deny-list itself is only allowed inside this test file.
FORBIDDEN_BRAND_TOKENS = (
    "modex",
    "mhcoding",
    "mingheng.xin",
    "modex-mh-agent",
    "x-mh-session-token",
    "mh_local_session_token",
    "mh_runtime_root",
    "mh_desktop",
    # Imported research-harness brand (must not ship as product identity).
    "aris_repo",
    "aris-research",
    "install_aris",
    "aris_repo",
)

_SCAN_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".ps1",
    ".sh",
    ".html",
    ".css",
    ".yml",
    ".yaml",
    ".toml",
    ".cmd",
    ".txt",
}
_SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "release",
    "dist",
    ".epipe-test-user-data",
    "verification-logs",
    "templates",  # third-party LaTeX class assets
    "fonts",
}


def _iter_product_files():
    roots = [
        ROOT / "backend",
        ROOT / "frontend" / "src",
        ROOT / "skills",
        ROOT / "tools",
        ROOT / "scripts",
        ROOT / "tests",
        ROOT / "docs",
        ROOT / "main.js",
        ROOT / "preload.js",
        ROOT / "updater.js",
        ROOT / "updater-config.json",
        ROOT / "package.json",
        ROOT / "desktop-data.js",
    ]
    for root in roots:
        if root.is_file():
            yield root
            continue
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            # Skip only relative segments under the scan root (not parents like "frontend").
            try:
                rel_parts = path.relative_to(root).parts
            except ValueError:
                rel_parts = path.parts
            if any(part in _SKIP_DIR_NAMES for part in rel_parts[:-1]):
                continue
            if path.suffix.lower() not in _SCAN_SUFFIXES and path.name not in {
                "main.js",
                "preload.js",
                "updater.js",
                "desktop-data.js",
            }:
                continue
            yield path


def test_vibe_identity_has_no_legacy_update_or_session_defaults():
    files = [
        ROOT / "main.js",
        ROOT / "updater.js",
        ROOT / "updater-config.json",
        ROOT / "backend" / "config.py",
        ROOT / "backend" / "services" / "local_session.py",
        ROOT / "frontend" / "src" / "api.ts",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for forbidden in (
        "mingheng.xin",
        "X-MH-Session-Token",
        "MH_LOCAL_SESSION_TOKEN",
        "MH_RUNTIME_ROOT",
        "MH_DESKTOP",
        "modex-mh-agent",
    ):
        assert forbidden not in text
    config = json.loads((ROOT / "updater-config.json").read_text(encoding="utf-8"))
    assert config["enabled"] is False and config["server_url"] is None


def test_windows_metadata_declares_vibe_research_identity():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["build"]["productName"] == "Vibe Research"
    assert package["build"]["executableName"] == "Vibe Research"
    assert package["build"]["win"]["signAndEditExecutable"] is False
    assert "blocked_external_certificate_required" in (ROOT / "scripts" / "Build-Release.ps1").read_text(
        encoding="utf-8"
    )
    assert (ROOT / "scripts" / "Set-WindowsIdentity.ps1").is_file()
    assert (ROOT / "scripts" / "Write-ReleaseMetadata.ps1").is_file()
    assert "OriginalFilename 'Vibe Research.exe'" in (ROOT / "scripts" / "Set-WindowsIdentity.ps1").read_text(
        encoding="utf-8"
    )


def test_product_tree_has_zero_competitor_brand_tokens():
    """Tree scan: Modex/MHcoding/ARIS brand tokens must be zero outside allowlist."""
    allowlist = {
        (ROOT / "tests" / "test_product_identity.py").resolve(),
        # One-shot rebrand helper may mention old tokens in comments/docs only if present.
        (ROOT / "tools" / "_rebrand_aris_to_vibe.py").resolve(),
    }
    # Legacy SQLite filename is allowed only as migration source in these two files.
    legacy_db_allow = {
        (ROOT / "backend" / "config.py").resolve(),
        (ROOT / "desktop-data.js").resolve(),
    }
    # Patterns that catch brand leakage without false-positive on common words.
    patterns = [
        re.compile(r"\bmodex\b", re.I),
        re.compile(r"\bmhcoding\b", re.I),
        re.compile(r"mingheng\.xin", re.I),
        re.compile(r"modex-mh-agent", re.I),
        re.compile(r"X-MH-Session-Token"),
        re.compile(r"\bMH_LOCAL_SESSION_TOKEN\b"),
        re.compile(r"\bMH_RUNTIME_ROOT\b"),
        re.compile(r"\bMH_DESKTOP\b"),
        re.compile(r"\bARIS_REPO\b"),
        re.compile(r"\bARIS_CONDA_HOOK\b"),
        re.compile(r"install_aris(?:_codex)?\.sh"),
        re.compile(r"aris-research", re.I),
        re.compile(r"~/aris_repo"),
        re.compile(r"(?<![A-Za-z])\.aris(?![A-Za-z])"),
        re.compile(r"\bARIS\b"),
    ]
    hits: list[str] = []
    scanned = 0
    for path in _iter_product_files():
        resolved = path.resolve()
        if resolved in allowlist:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        if resolved in legacy_db_allow:
            # Keep only the on-disk migration filename; strip it before brand scan.
            text = text.replace("aris.db", "LEGACY_DB_FILENAME")
        for pattern in patterns:
            if pattern.search(text):
                rel = path.relative_to(ROOT).as_posix()
                hits.append(f"{rel}: matched {pattern.pattern}")
                break
    assert scanned >= 50, f"identity scan too shallow: scanned={scanned}"
    assert hits == [], "competitor brand tokens found:\n" + "\n".join(hits[:40])


def test_skill_owned_tex_templates_have_zero_competitor_brand():
    """LaTeX skill templates are product surfaces; do not skip brand scan entirely.

    Third-party .cls/.sty packages under templates/ may still be skipped, but
    skill-owned .tex headers/bodies must not ship ARIS/Modex brand tokens.
    """
    patterns = [
        re.compile(r"\bmodex\b", re.I),
        re.compile(r"\bmhcoding\b", re.I),
        re.compile(r"mingheng\.xin", re.I),
        re.compile(r"\bARIS\b"),
        re.compile(r"aris-research", re.I),
        re.compile(r"install_aris", re.I),
    ]
    hits: list[str] = []
    scanned = 0
    for path in (ROOT / "skills").rglob("*.tex"):
        if not path.is_file():
            continue
        # Venue class packages / third-party bodies: still scan for brand only.
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for pattern in patterns:
            if pattern.search(text):
                rel = path.relative_to(ROOT).as_posix()
                hits.append(f"{rel}: matched {pattern.pattern}")
                break
    assert scanned >= 5, f"tex brand scan too shallow: scanned={scanned}"
    assert hits == [], "competitor brand tokens in skill .tex templates:\n" + "\n".join(hits[:40])


def test_package_declares_canonical_vibe_research_namespace():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == "vibe-research"
    assert package["author"] == "Vibe Research Project"
    assert package["build"]["appId"] == "com.viberesearch.workbench"
    assert package["build"]["artifactName"] == "Vibe-Research-${version}-Setup.${ext}"
