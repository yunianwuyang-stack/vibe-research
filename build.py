"""Build script for the Vibe Research desktop project.

Usage:
    python build.py          # Install dependencies and verify imports
    python build.py --clean  # Clean build: remove all caches, reinstall deps, verify
"""
import os
import subprocess
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
RUNTIME_PYTHON = PROJECT_ROOT / "runtime" / "python" / "python.exe"


def get_python():
    """Return the Python executable to use."""
    if RUNTIME_PYTHON.exists():
        return str(RUNTIME_PYTHON)
    return sys.executable


def clean():
    """Remove all caches and build artifacts."""
    print("[build] Cleaning...")
    # Remove __pycache__ directories
    for d in PROJECT_ROOT.rglob("__pycache__"):
        shutil.rmtree(str(d), ignore_errors=True)
    # Remove cache bytecode only.  Packaged tools may intentionally ship as
    # sourceless top-level ``.pyc`` files and are required at runtime.
    for f in PROJECT_ROOT.rglob("*.pyc"):
        if "__pycache__" not in f.parts:
            continue
        try:
            f.unlink()
        except:
            pass
    print("[build] Clean complete")


def install_deps():
    """Install Python dependencies."""
    python = get_python()
    req_path = BACKEND_DIR / "requirements.txt"
    print(f"[build] Installing dependencies from {req_path}...")
    result = subprocess.run([python, "-m", "pip", "install", "-r", str(req_path)], capture_output=True, text=True)
    print(result.stdout[-2000:] if result.stdout else "")
    if result.stderr:
        print(result.stderr[-2000:])
    if result.returncode != 0:
        print("[build] WARNING: pip install returned non-zero, some packages may be missing")
    else:
        print("[build] Dependencies installed")


def verify_imports():
    """Verify all backend modules can be imported."""
    python = get_python()
    print("[build] Verifying imports...")
    result = subprocess.run(
        [python, "-c", """
import sys, os
project_root = os.getcwd()
sys.path.insert(0, os.path.join(project_root, 'backend'))
os.chdir(os.path.join(project_root, 'backend'))

modules = [
    'config', 'models.schemas', 'models',
    'services.state_store', 'services.workflow_engine', 'services.claude_runner',
    'services.llm_client', 'services.license_guard', 'services.skill_crypto',
    'services.editor_ai', 'services.extract_worker', 'services.docx_tool_loader',
    'services.prompts',
    'routers.workflows', 'routers.artifacts', 'routers.checkpoints',
    'routers.settings', 'routers.editor', 'routers.ws', 'routers.docx_export',
    'routers',
]
errors = []
for m in modules:
    try:
        __import__(m)
        print(f"  OK: {m}")
    except Exception as e:
        errors.append((m, str(e)))
        print(f"  FAIL: {m} -> {e}")

if errors:
    print(); print(f"{len(errors)} import errors!")
    sys.exit(1)
else:
    print(); print(f"All {len(modules)} modules imported successfully!")
"""],
        cwd=str(PROJECT_ROOT),
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode == 0


def verify_routes():
    """Verify FastAPI app can be created with all routes."""
    python = get_python()
    print("[build] Verifying FastAPI app...")
    result = subprocess.run(
        [python, "-c", """
import sys, os
project_root = os.getcwd()
sys.path.insert(0, os.path.join(project_root, 'backend'))
os.chdir(os.path.join(project_root, 'backend'))
from main import app
routes = [r for r in app.routes if hasattr(r, 'path') and r.path.startswith('/api/')]
print(f"API routes: {len(routes)}")
for r in sorted(routes, key=lambda x: x.path):
    methods = list(getattr(r, 'methods', []) or [])
    print(f"  {' '.join(methods) or 'WS':10s} {r.path:60s} {getattr(r, 'name', '?')}")
print(); print("FastAPI app created successfully!")
"""],
        cwd=str(PROJECT_ROOT),
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    return result.returncode == 0


def build(clean_build=False):
    """Run the full build process."""
    if clean_build:
        clean()
    install_deps()
    
    ok = verify_imports()
    if not ok:
        print("[build] Import verification FAILED")
        return False
    
    ok = verify_routes()
    if not ok:
        print("[build] Route verification FAILED")
        return False
    
    print("[build] Build successful!")
    return True


if __name__ == "__main__":
    clean_build = "--clean" in sys.argv
    success = build(clean_build)
    sys.exit(0 if success else 1)
