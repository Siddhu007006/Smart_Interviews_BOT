#!/usr/bin/env python3
"""
Phase 1 Setup Helper Script

Guides you through setting up the bot for the first time.
Run this before running the bot: python setup_phase1.py
"""

import os
import sys
import subprocess
from pathlib import Path

def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def check_python():
    print("✓ Checking Python version...")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 10:
        print(f"  ✓ Python {version.major}.{version.minor} OK")
        return True
    else:
        print(f"  ✗ Python {version.major}.{version.minor} - need 3.10+")
        return False

def check_chrome():
    print("✓ Checking Chrome installation...")
    chrome_paths = [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
    ]
    
    for path in chrome_paths:
        if os.path.exists(path):
            print(f"  ✓ Chrome found at: {path}")
            return True
    
    print(f"  ✗ Chrome not found. Please install Chrome from google.com/chrome")
    return False

def check_env_file():
    print("✓ Checking .env file...")
    if os.path.exists(".env"):
        print("  ✓ .env file exists")
        # Check required fields
        with open(".env") as f:
            content = f.read()
            required = ["HIVE_LOGIN_URL", "HIVE_USERNAME", "HIVE_PASSWORD"]
            missing = [r for r in required if r not in content or f"{r}=" not in content]
            if missing:
                print(f"  ✗ Missing in .env: {', '.join(missing)}")
                print(f"  → Fill these in .env file")
                return False
            print("  ✓ Required fields present")
            return True
    else:
        print("  ✗ .env file not found")
        print("  → Run: cp .env.example .env")
        print("  → Then fill in your credentials")
        return False

def check_requirements():
    print("✓ Checking Python dependencies...")
    try:
        import playwright
        print("  ✓ Playwright installed")
        return True
    except ImportError:
        print("  ✗ Playwright not installed")
        print("  → Run: pip install -r requirements.txt")
        return False

def check_playwright_browsers():
    print("✓ Checking Playwright browsers...")
    # This is a simple check - more thorough would actually try to launch
    try:
        import subprocess
        result = subprocess.run(
            ["python", "-m", "playwright", "install", "--with-deps"],
            capture_output=True,
            text=True,
            timeout=300
        )
        print("  ✓ Playwright browsers ready")
        return True
    except Exception as e:
        print(f"  ✗ Error setting up browsers: {e}")
        print("  → Run: python -m playwright install")
        return False

def print_next_steps():
    print_header("NEXT STEPS")
    print("""
1. Configure .env file with your Hive credentials:
   export HIVE_LOGIN_URL="https://hive.smartinterviews.in/contests/..."
   export HIVE_USERNAME="your_username"
   export HIVE_PASSWORD="your_password"
   
2. Install Hive Extension Detector:
   - Go to: https://chrome.google.com/webstore/
   - Search: "Hive Extension Detector"
   - Click: "Add to Chrome"
   
3. Run Phase 1:
   python -m src.main --log-level DEBUG
   
4. Open DevTools (F12) and inspect the problem list:
   - Right-click on elements
   - Copy selectors
   - Document in src/hive/ui_constants.py
   
5. Read the full guide:
   cat PHASE1_LIVE_TESTING.md
""")

def main():
    print_header("PHASE 1 SETUP CHECK")
    
    checks = [
        ("Python 3.10+", check_python),
        ("Chrome Browser", check_chrome),
        (".env Configuration", check_env_file),
        ("Python Dependencies", check_requirements),
        ("Playwright Browsers", check_playwright_browsers),
    ]
    
    results = []
    for name, check in checks:
        try:
            result = check()
            results.append((name, result))
        except Exception as e:
            print(f"  ✗ Error: {e}")
            results.append((name, False))
    
    print_header("SETUP SUMMARY")
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    if all(r for _, r in results):
        print_header("YOU'RE READY!")
        print("All checks passed. Ready to run Phase 1:")
        print("\n  python -m src.main --log-level DEBUG\n")
    else:
        print_header("SETUP INCOMPLETE")
        print("Fix the failed checks above, then run this script again.\n")
        print_next_steps()
    
    return 0 if all(r for _, r in results) else 1

if __name__ == "__main__":
    sys.exit(main())
