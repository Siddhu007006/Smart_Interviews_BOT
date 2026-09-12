#!/usr/bin/env python3
"""
Hive Bot Launcher - Ensures Python 3.12 is used and dynamically locates local virtual environment.
"""
import sys
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Ensure we are executing inside the virtual environment
in_venv = (sys.prefix != sys.base_prefix)

if not in_venv or sys.version_info < (3, 12):
    # Look for virtual environment dynamically in project root
    candidate_venvs = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / "venv_312" / "Scripts" / "python.exe",
        PROJECT_ROOT / "venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "bin" / "python",
        PROJECT_ROOT / "venv" / "bin" / "python",
    ]

    target_python = None
    for cand in candidate_venvs:
        if cand.exists():
            target_python = cand
            break

    if target_python and Path(sys.executable).resolve() != target_python.resolve():
        sys.exit(subprocess.call([str(target_python), __file__] + sys.argv[1:]))
    elif sys.version_info < (3, 12):
        print(f"ERROR: Python {sys.version_info.major}.{sys.version_info.minor} detected.")
        print(f"This project requires Python 3.12+ in a virtual environment.")
        print(f"Could not locate a virtual environment in {PROJECT_ROOT}")
        sys.exit(1)

# Ensure project root is in sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Now import and run the bot
try:
    from src.main import cli_main
    cli_main()
except ImportError as e:
    print(f"ERROR: Could not import bot module: {e}")
    print(f"Make sure you are executing from {PROJECT_ROOT}")
    sys.exit(1)
