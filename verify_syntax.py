#!/usr/bin/env python
"""
Simple syntax verification script.
Imports all modules to check for import/syntax errors.
"""

import sys
from pathlib import Path

def verify_imports():
    """Verify all modules can be imported"""
    errors = []
    
    try:
        print("Verifying module imports...")
        
        # Utils
        print("  - src.utils...")
        import src.utils
        
        # Browser
        print("  - src.browser...")
        import src.browser
        
        # Auth
        print("  - src.auth...")
        import src.auth
        
        # Hive
        print("  - src.hive...")
        import src.hive
        
        # State
        print("  - src.state...")
        import src.state
        
        # Main
        print("  - src.bot...")
        import src.bot
        
        print("  - src.main...")
        import src.main
        
        print("✓ All imports successful")
        return True
        
    except Exception as e:
        print(f"✗ Import error: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_files():
    """Check that all expected files exist"""
    print("\nVerifying file structure...")
    
    files = [
        "src/__init__.py",
        "src/utils/__init__.py",
        "src/utils/config.py",
        "src/utils/errors.py",
        "src/utils/constants.py",
        "src/utils/logging_config.py",
        "src/browser/__init__.py",
        "src/browser/manager.py",
        "src/browser/extension.py",
        "src/auth/__init__.py",
        "src/auth/credentials.py",
        "src/auth/login.py",
        "src/hive/__init__.py",
        "src/hive/dom_queries.py",
        "src/hive/ui_constants.py",
        "src/hive/problem_list.py",
        "src/state/__init__.py",
        "src/state/models.py",
        "src/state/manager.py",
        "src/bot.py",
        "src/main.py",
        "config/default_config.yaml",
        "tests/__init__.py",
        "tests/conftest.py",
        "tests/test_config.py",
        "tests/test_browser_manager.py",
    ]
    
    base = Path(".")
    missing = []
    
    for file in files:
        path = base / file
        if path.exists():
            print(f"  ✓ {file}")
        else:
            print(f"  ✗ {file} MISSING")
            missing.append(file)
    
    return len(missing) == 0

if __name__ == "__main__":
    files_ok = check_files()
    imports_ok = verify_imports()
    
    if files_ok and imports_ok:
        print("\n✓ Phase 1 implementation verified successfully!")
        sys.exit(0)
    else:
        print("\n✗ Phase 1 verification failed")
        sys.exit(1)
