#!/usr/bin/env python3
"""
Hive Bot Launcher - Ensures Python 3.12 is used
"""
import sys
import subprocess

if sys.version_info < (3, 12):
    print(f"ERROR: Python {sys.version_info.major}.{sys.version_info.minor} detected")
    print("This project requires Python 3.12+")
    print("")
    print("Switching to Python 3.12 from venv...")
    
    # Run with Python 3.12 from venv
    import os
    venv_python = r"d:\bot\venv_312\Scripts\python.exe"
    if os.path.exists(venv_python):
        sys.exit(subprocess.call([venv_python, __file__] + sys.argv[1:]))
    else:
        print(f"ERROR: Could not find {venv_python}")
        sys.exit(1)

# If we get here, we're running on Python 3.12+
print(f"Python {sys.version_info.major}.{sys.version_info.minor} confirmed")

# Now import and run the bot
try:
    from src.main import main
    sys.exit(main())
except ImportError as e:
    print(f"ERROR: Could not import bot module: {e}")
    print("Make sure you're in the d:\\bot directory")
    sys.exit(1)
