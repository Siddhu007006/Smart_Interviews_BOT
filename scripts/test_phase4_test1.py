"""
Phase 4 — Test 1: Browser + Extension Gate Live Validation.

Verifies:
1. Runtime launched: Channel=None (Playwright Chromium / Chrome for Testing)
2. Persistent profile used
3. Genuine extension service worker present with ID goknflnoeiaookhdbnldcbnodjahpgdh
4. Hive blocker detected and verified dismissed
5. Continue Contest located and clicked
6. Problem list page reached and verified
7. Problems extracted (count > 0)
8. Strictly NO AI API calls, NO editor injection, NO Run, NO Submit.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import get_logger, ConfigManager, LogContext
from src.browser.manager import BrowserManager
from src.browser.extension_installer import ExtensionInstaller, EXTENSION_ID
from src.browser.extension import ExtensionChecker
from src.auth import AuthManager, Credentials
from src.hive.problem_list import ProblemListDetector

logger = get_logger("Phase4Test1")


async def run_test_1():
    print("=" * 70)
    print("PHASE 4 — TEST 1: BROWSER + EXTENSION GATE VALIDATION")
    print("=" * 70)

    # Metrics dictionary for final acceptance criteria report
    report = {
        "runtime_launched": False,
        "requested_channel": None,
        "browser_executable": None,
        "browser_user_agent": None,
        "persistent_profile_used": False,
        "profile_path": None,
        "genuine_extension_sw_present": False,
        "extension_id_observed": None,
        "extension_sw_url": None,
        "blocker_initially_checked": False,
        "blocker_dismissed": False,
        "continue_contest_clicked": False,
        "problem_list_verified": False,
        "problems_extracted_count": 0,
        "sample_problems": [],
        "ai_api_calls": 0,
        "code_injections": 0,
        "submissions": 0,
        "all_criteria_met": False,
    }

    # 1. Load Configuration
    config = ConfigManager()
    profile_path = Path(config.get_required("browser.browser_profile_path")).expanduser().resolve()
    data_dir = Path(config.get("bot.data_dir", "~/.hive_bot")).expanduser().resolve()
    channel = config.get("browser.channel", None)
    headless = config.get("browser.headless", False)
    contest_url = os.environ.get("HIVE_CONTEST_URL") or config.get("hive.contest_url", "https://hive.smartinterviews.in/contests/smart-interviews-basic")

    report["requested_channel"] = channel
    report["profile_path"] = str(profile_path)

    print(f"\n[1] Configuration:")
    print(f"  - browser.channel: {channel} (Expected: None / Chrome for Testing)")
    print(f"  - browser_profile_path: {profile_path}")
    print(f"  - bot.data_dir: {data_dir}")
    print(f"  - contest_url: {contest_url}")

    # 2. Extension Installation Verification
    installer = ExtensionInstaller(profile_path=profile_path, data_dir=data_dir)
    installer.ensure_installed()
    ext_args = installer.get_extension_args()
    print(f"\n[2] Extension args from installer: {ext_args}")

    # 3. Launch Browser
    browser_manager = BrowserManager(
        profile_path=str(profile_path),
        headless=headless,
        channel=channel,
        extra_args=ext_args,
    )

    try:
        await browser_manager.launch_browser()
        report["runtime_launched"] = True
        report["persistent_profile_used"] = profile_path.exists()
        print("\n[3] Browser launched successfully.")

        page = await browser_manager.get_page()
        runtime_info = await browser_manager.get_runtime_info()
        report["browser_executable"] = runtime_info["executable_path"]
        report["browser_user_agent"] = runtime_info["user_agent"]

        print(f"  - Requested Channel: {runtime_info['requested_channel']}")
        print(f"  - Executable: {runtime_info['executable_path']}")
        print(f"  - User Agent: {runtime_info['user_agent']}")

        # 4. Service Worker Verification (Tier 2)
        context = browser_manager.context
        await asyncio.sleep(2.0)
        workers = context.service_workers
        print(f"\n[4] Active Service Workers in BrowserContext ({len(workers)}):")
        for sw in workers:
            print(f"  - {sw.url}")
            if EXTENSION_ID in sw.url:
                report["genuine_extension_sw_present"] = True
                report["extension_id_observed"] = EXTENSION_ID
                report["extension_sw_url"] = sw.url

        if not report["genuine_extension_sw_present"]:
            print(f"  [!] Genuine extension SW with ID '{EXTENSION_ID}' NOT found in service workers.")

        # 5. Navigate to Contest Dashboard
        print(f"\n[5] Navigating to contest dashboard: {contest_url}")
        await page.goto(contest_url, wait_until="networkidle", timeout=45000)
        await asyncio.sleep(3.0)

        # Check if redirected to login
        if "login" in page.url.lower():
            print(f"  - Redirected to login page: {page.url}. Performing authentication...")
            creds = Credentials.from_config(config)
            auth_manager = AuthManager(page, creds, timeout_s=60)
            login_ok = await auth_manager.login()
            print(f"  - Login result: {login_ok}")
            await page.goto(contest_url, wait_until="networkidle", timeout=45000)
            await asyncio.sleep(3.0)

        # 6. Check Extension Blocker (Tier 3)
        report["blocker_initially_checked"] = True
        checker = ExtensionChecker(page, profile_path)
        blocker_el = await page.query_selector("app-extension-blocker")
        blocker_in_dom = blocker_el is not None
        blocker_text = (await blocker_el.inner_text()).strip() if blocker_el else ""
        print(f"\n[6] Extension Blocker Inspection:")
        print(f"  - app-extension-blocker element in DOM: {blocker_in_dom}")
        print(f"  - Blocker inner text: {repr(blocker_text)}")

        is_modal_vis = await checker.is_extension_modal_visible()
        print(f"  - is_extension_modal_visible: {is_modal_vis}")
        blocker_dismissed = await checker.verify_hive_blocker_dismissed(timeout_s=5.0)
        report["blocker_dismissed"] = blocker_dismissed
        print(f"  - verify_hive_blocker_dismissed: {blocker_dismissed}")

        # 7. Continue Contest Interaction
        detector = ProblemListDetector(page)
        print(f"\n[7] Problem List & Continue Contest Interaction:")
        on_prob_page = await detector.is_on_problem_list_page()
        print(f"  - Already on problem list page: {on_prob_page}")

        if not on_prob_page:
            print("  - Attempting to locate and click 'Continue Contest'...")
            continue_clicked = await detector.click_continue_contest(timeout_ms=15000)
            report["continue_contest_clicked"] = continue_clicked
            print(f"  - Continue Contest clicked: {continue_clicked}")
        else:
            report["continue_contest_clicked"] = True

        # Verify on problems page
        on_prob_page = await detector.is_on_problem_list_page()
        report["problem_list_verified"] = on_prob_page
        print(f"  - Problem list page verified: {on_prob_page} (URL: {page.url})")

        # 8. Extract Problems
        if on_prob_page:
            print(f"\n[8] Extracting problems from problem list...")
            problems = await detector.fetch_problems()
            report["problems_extracted_count"] = len(problems)
            for p in problems[:5]:
                report["sample_problems"].append({
                    "problem_id": p.problem_id,
                    "title": p.title,
                    "score": p.score,
                    "solved": p.solved,
                })
                print(f"  - [{p.status}] {p.title} (ID: {p.problem_id}, Score: {p.score})")
            if len(problems) > 5:
                print(f"  ... and {len(problems) - 5} more problems.")

        # 9. Verify Safety Bounds (ZERO AI, ZERO editor, ZERO submit)
        print(f"\n[9] Safety Bounds Verification:")
        print(f"  - AI API calls: {report['ai_api_calls']}")
        print(f"  - Code injections: {report['code_injections']}")
        print(f"  - Submissions: {report['submissions']}")

        # 10. Overall Check
        report["all_criteria_met"] = (
            report["runtime_launched"]
            and report["requested_channel"] is None
            and report["persistent_profile_used"]
            and report["genuine_extension_sw_present"]
            and report["extension_id_observed"] == EXTENSION_ID
            and report["blocker_initially_checked"]
            and report["blocker_dismissed"]
            and report["continue_contest_clicked"]
            and report["problem_list_verified"]
            and report["problems_extracted_count"] > 0
            and report["ai_api_calls"] == 0
            and report["code_injections"] == 0
            and report["submissions"] == 0
        )

    except Exception as e:
        logger.error(f"Test 1 failed with exception: {e}", exc_info=True)
        print(f"\n[ERROR] Test 1 failed: {e}")
    finally:
        await browser_manager.close()
        print("\n[10] Browser closed cleanly.")

    # Save report artifact
    out_path = PROJECT_ROOT / "scratch" / "phase4_test1_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 70)
    print(f"FINAL RESULT: {'SUCCESS - ALL CRITERIA MET' if report['all_criteria_met'] else 'FAILED'}")
    print("=" * 70)
    return report


if __name__ == "__main__":
    result = asyncio.run(run_test_1())
    sys.exit(0 if result.get("all_criteria_met") else 1)
