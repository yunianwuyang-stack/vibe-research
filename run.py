"""Run the Vibe Research backend server.

Usage:
    python run.py              # Start the backend server
    python run.py --port 8080  # Start on a custom port
"""
import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
RUNTIME_PYTHON = PROJECT_ROOT / "runtime" / "python" / "python.exe"


def get_python():
    """Return the Python executable to use."""
    if RUNTIME_PYTHON.exists():
        return str(RUNTIME_PYTHON)
    return sys.executable


def main():
    port = 18088
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    
    os.environ.setdefault("VIBE_DESKTOP", "1")
    os.environ.setdefault("API_PORT", str(port))
    os.environ.setdefault("PYTHONPATH", str(BACKEND_DIR))
    
    python = get_python()
    print(f"[run] Starting backend on port {port}...")
    print(f"[run] Python: {python}")
    print(f"[run] Backend dir: {BACKEND_DIR}")
    
    # Start uvicorn
    cmd = [python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)]
    subprocess.run(cmd, cwd=str(BACKEND_DIR))


if __name__ == "__main__":
    main()
