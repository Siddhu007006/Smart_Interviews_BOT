"""
Phase 4 — Test 3: One Real Problem, Live Submission & State Persistence.

Validates the full end-to-end solve & submit pipeline on ONE real problem:
Extract ProblemDetail
  ↓
Select C++ & Verify
  ↓
Detect & Bind Monaco Editor Instance
  ↓
AI Code Generation (via configured model, zero hardcoding)
  ↓
SolutionValidator Sanity & Normalization
  ↓
Inject Code to Monaco
  ↓
Read back from Monaco & Verify Normalized Match
  ↓
Run Sample Tests on Live Hive
  ↓
Submit ONCE (dry_run=False)
  ↓
Poll and Parse Actual Submission Verdict (Console / Toast / Score)
  ↓
Atomic Checkpoint to Isolated State File (state_test3.json)
  ↓
Verify State Post-Conditions (completed_problems, problems_queue)
  ↓
STOP (No multi-problem processing, no Test 4)
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import get_logger, ConfigManager, SubmissionError
from src.browser.manager import BrowserManager
from src.browser.extension_installer import ExtensionInstaller
from src.browser.extension import ExtensionChecker
from src.auth import AuthManager, Credentials
from src.hive.problem_detail import ProblemDetailParser, ProblemDetail
from src.editor.language_controller import LanguageController
from src.editor.detector import EditorDetector
from src.editor.adapter import normalize_code
from src.solver.engine import AISolverEngine
from src.solver.models import SolutionRequest, SolutionResponse
from src.solver.validator import SolutionValidator
from src.hive.submission import SubmissionManager, SubmissionResult, RunResult, Verdict
from src.state.manager import StateManager

logger = get_logger("Phase4Test3")


async def run_test_3():
    print("=" * 70)
    print("PHASE 4 — TEST 3: ONE REAL PROBLEM, LIVE SUBMISSION VALIDATION")
    print("=" * 70)

    isolated_state_file = PROJECT_ROOT / "scratch" / "state_test3.json"
    isolated_state_file.parent.mkdir(parents=True, exist_ok=True)

    # Ensure fresh isolated state file
    if isolated_state_file.exists():
        isolated_state_file.unlink()

    state_manager = StateManager(state_file=isolated_state_file)
    problem_slug = "gauntlets"
    problem_title = "Gauntlets"

    # Pre-condition check: add problem to queue
    state_manager.add_problem(problem_slug, problem_title)
    assert problem_slug not in state_manager.state.completed_problems, "Precondition violated: problem already completed"
    assert problem_slug in state_manager.state.problems_queue, "Precondition violated: problem not in queue"
    print(f"  [state] Isolated state initialized at: {isolated_state_file}")
    print(f"  [state] Precondition verified: {problem_slug} is queued and not completed.")

    report = {
        "problem_extraction": {},
        "language_selection": {},
        "editor_binding": {},
        "ai_generation": {},
        "code_injection": {},
        "sample_execution": {},
        "submission_execution": {},
        "state_verification": {},
        "safety_audit": {
            "ai_calls": 0,
            "editor_injections": 0,
            "runs": 0,
            "submits": 0,
            "isolated_state_used": str(isolated_state_file),
            "production_state_untouched": True,
        },
        "final_state": "PENDING",
        "all_criteria_met": False,
    }

    # Explicitly load .env from project root
    from dotenv import load_dotenv
    dotenv_path = PROJECT_ROOT / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)
        print(f"  [env] Loaded .env from {dotenv_path}")
    else:
        print(f"  [env] WARNING: .env not found at {dotenv_path}")

    config = ConfigManager()
    profile_path = Path(config.get_required("browser.browser_profile_path")).expanduser().resolve()
    data_dir = Path(config.get("bot.data_dir", "~/.hive_bot")).expanduser().resolve()
    channel = config.get("browser.channel", None)
    headless = config.get("browser.headless", False)

    # Check production state file modification time if it exists
    prod_state_path = data_dir / "state.json"
    prod_mtime_before = prod_state_path.stat().st_mtime if prod_state_path.exists() else None

    # Setup Extension Args & Browser
    installer = ExtensionInstaller(profile_path=profile_path, data_dir=data_dir)
    installer.ensure_installed()
    ext_args = installer.get_extension_args()

    browser_manager = BrowserManager(
        profile_path=str(profile_path),
        headless=headless,
        channel=channel,
        extra_args=ext_args,
    )

    try:
        await browser_manager.launch_browser()
        page = await browser_manager.get_page()

        target_url = "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems/gauntlets"
        print(f"\n[1] Navigating to problem: {target_url}")
        await page.goto(target_url, wait_until="commit", timeout=90000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(5.0)

        # Handle login if needed
        if "login" in page.url.lower():
            print("  - Session expired; performing login...")
            creds = Credentials.from_config(config)
            auth_manager = AuthManager(page, creds, timeout_s=60)
            await auth_manager.login()
            await page.goto(target_url, wait_until="commit", timeout=90000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            await asyncio.sleep(5.0)

        # Verify extension ready
        checker = ExtensionChecker(page, profile_path)
        await checker.verify_extension_ready(timeout_s=10.0)
        print("  - Extension gate verified and active.")

        # Extract Problem Details
        print("  - Waiting for problem DOM to render...")
        try:
            await page.wait_for_selector(".problem-title, h1, .problem-statement, .description", timeout=20000)
        except Exception:
            pass
        await asyncio.sleep(2.0)

        print("\n[2] Extracting Problem Detail from page...")
        problem_detail = await ProblemDetailParser.extract_from_page(page)

        report["problem_extraction"] = {
            "url": page.url,
            "problem_id": problem_detail.problem_id,
            "title": problem_detail.title,
            "statement": problem_detail.description[:300] + ("..." if len(problem_detail.description) > 300 else ""),
            "input_format": problem_detail.input_format,
            "output_format": problem_detail.output_format,
            "constraints": problem_detail.constraints,
            "sample_cases_count": len(problem_detail.sample_cases),
        }
        print(f"  - Problem ID: {problem_detail.problem_id}")
        print(f"  - Title: {problem_detail.title}")
        print(f"  - Sample cases count: {len(problem_detail.sample_cases)}")

        # Language Selection: C++
        print("\n[3] Controlling Editor Language...")
        lang_controller = LanguageController(page)
        current_lang = await lang_controller.get_current_language()
        print(f"  - Language before action: {current_lang}")

        target_lang = "C++"
        if current_lang != target_lang:
            success = await lang_controller.select_language(target_lang)
            print(f"  - Action: select_language('{target_lang}') -> returned={success}")

        verified_lang = await lang_controller.verify_language(target_lang)
        final_lang = await lang_controller.get_current_language()
        print(f"  - Language after action: {final_lang}")

        report["language_selection"] = {
            "initial_language": current_lang,
            "requested_language": target_lang,
            "final_language": final_lang,
            "verified_match": verified_lang,
        }

        # Editor Binding
        print("\n[4] Detecting and Binding Monaco Editor...")
        detector = EditorDetector(page)
        adapter = await detector.detect_and_bind()
        container_exists = await page.evaluate("() => Boolean(document.querySelector('#editor'))")
        initial_code = await adapter.get_code()

        report["editor_binding"] = {
            "adapter_type": type(adapter).__name__,
            "container_found": container_exists,
            "initial_code_snippet": initial_code[:100],
        }
        print(f"  - Container '#editor' found: {container_exists}")
        print(f"  - Bound editor type: {type(adapter).__name__}")

        # AI Code Generation
        print("\n[5] Generating Solution via AI Solver Engine...")
        engine = AISolverEngine(config)
        sol_request = SolutionRequest(
            problem_id=problem_detail.problem_id,
            title=problem_detail.title,
            description=problem_detail.description,
            input_format=problem_detail.input_format,
            output_format=problem_detail.output_format,
            constraints=problem_detail.constraints,
            sample_cases=problem_detail.sample_cases,
            language=target_lang,
            attempt_number=1,
        )

        report["safety_audit"]["ai_calls"] += 1
        sol_response = await engine.solve(sol_request)

        print(f"  - Provider used: {sol_response.provider}")
        print(f"  - Model used: {sol_response.model}")
        print(f"  - Code length: {len(sol_response.code)} chars")

        # SolutionValidator sanity check
        validated_code = SolutionValidator.clean_and_validate(sol_response.code, target_lang)
        validator_accepted = bool(validated_code)

        report["ai_generation"] = {
            "provider": sol_response.provider,
            "model": sol_response.model,
            "code_length": len(sol_response.code),
            "code_preview": sol_response.code[:300],
            "validator_accepted": validator_accepted,
        }

        # Code Injection & Readback Verification
        print("\n[6] Injecting Code into Monaco Editor & Verifying Readback...")
        await adapter.set_code(sol_response.code)
        report["safety_audit"]["editor_injections"] += 1

        readback_code = await adapter.get_code()
        norm_expected = normalize_code(sol_response.code)
        norm_readback = normalize_code(readback_code)
        readback_match = (norm_expected == norm_readback)

        report["code_injection"] = {
            "injected": True,
            "readback_succeeded": bool(readback_code.strip()),
            "normalized_match": readback_match,
            "readback_length": len(readback_code),
        }
        print(f"  - Readback length: {len(readback_code)} chars")
        print(f"  - Normalized readback match: {readback_match}")

        # Sample Run
        print("\n[7] Executing Sample Run...")
        sub_mgr = SubmissionManager(run_timeout_s=35.0, submit_timeout_s=60.0, dry_run=False)
        report["safety_audit"]["runs"] += 1
        run_result = await sub_mgr.run_sample_tests(page)

        print(f"  - Sample Run success: {run_result.success}")
        print(f"  - Sample Verdict: {run_result.verdict.value}")
        report["sample_execution"] = {
            "success": run_result.success,
            "verdict": run_result.verdict.value,
            "sample_cases_count": len(run_result.sample_cases),
            "diagnostic_message": run_result.diagnostic_message,
        }

        # Single Live Submission
        print("\n[8] Executing LIVE Submission (ONCE, dry_run=False)...")
        report["safety_audit"]["submits"] += 1
        sub_result = await sub_mgr.submit_solution(page)

        print(f"  - Submission Result Success: {sub_result.success}")
        print(f"  - Submission Verdict: {sub_result.verdict.value}")
        print(f"  - Score: {sub_result.score} / {sub_result.max_score}")
        print(f"  - Test cases passed: {sub_result.testcases_passed} / {sub_result.total_testcases}")
        print(f"  - Diagnostic Message: {sub_result.diagnostic_message}")

        # Take screenshot of submission result
        screenshot_path = PROJECT_ROOT / "scratch" / "test3_submission_result.png"
        await page.screenshot(path=str(screenshot_path))
        print(f"  - Submission screenshot saved to: {screenshot_path}")

        report["submission_execution"] = {
            "success": sub_result.success,
            "verdict": sub_result.verdict.value,
            "score": sub_result.score,
            "max_score": sub_result.max_score,
            "testcases_passed": sub_result.testcases_passed,
            "total_testcases": sub_result.total_testcases,
            "diagnostic_message": sub_result.diagnostic_message,
            "error_kind": sub_result.error_kind.value if sub_result.error_kind else None,
            "screenshot": str(screenshot_path),
        }

        # State Persistence & Post-Condition Audit
        print("\n[9] Evaluating State Persistence & Post-Conditions...")
        if sub_result.success or sub_result.verdict == Verdict.ACCEPTED:
            state_manager.mark_problem_solved(problem_slug)
            if problem_slug in state_manager.state.problems_queue:
                state_manager.state.problems_queue.remove(problem_slug)
            state_manager.save_state()
            print("  ✓ Problem marked solved in isolated state and removed from queue.")

        # Post-condition verifications
        in_completed = problem_slug in state_manager.state.completed_problems
        not_in_queue = problem_slug not in state_manager.state.problems_queue
        state_file_valid = isolated_state_file.exists() and isolated_state_file.stat().st_size > 0

        # Verify on-disk JSON file
        with open(isolated_state_file, "r", encoding="utf-8") as f:
            disk_state = json.load(f)
        disk_completed = problem_slug in disk_state.get("completed_problems", [])
        disk_not_queued = problem_slug not in disk_state.get("problems_queue", [])

        # Production state verification: ensure prod state file was not touched
        prod_mtime_after = prod_state_path.stat().st_mtime if prod_state_path.exists() else None
        prod_untouched = (prod_mtime_before == prod_mtime_after)

        print(f"  - Completed problems contains {problem_slug}: {in_completed} (disk: {disk_completed})")
        print(f"  - Queue no longer contains {problem_slug}: {not_in_queue} (disk: {disk_not_queued})")
        print(f"  - Isolated state JSON valid on disk: {state_file_valid}")
        print(f"  - Production state untouched: {prod_untouched}")

        report["state_verification"] = {
            "in_completed_memory": in_completed,
            "in_completed_disk": disk_completed,
            "not_in_queue_memory": not_in_queue,
            "not_in_queue_disk": disk_not_queued,
            "isolated_state_file_valid": state_file_valid,
            "production_state_untouched": prod_untouched,
        }

        if (sub_result.success or sub_result.verdict == Verdict.ACCEPTED) and in_completed and not_in_queue and prod_untouched:
            report["final_state"] = "SUBMISSION_ACCEPTED"
            report["all_criteria_met"] = True
        else:
            report["final_state"] = f"SUBMISSION_{sub_result.verdict.value.upper()}"
            report["all_criteria_met"] = False

    except Exception as e:
        logger.error(f"Test 3 failed with exception: {e}", exc_info=True)
        print(f"\n[ERROR] Test 3 failed: {e}")
        report["final_state"] = "FAILED"
    finally:
        await browser_manager.close()
        print("\n[10] Browser closed cleanly.")

    # Save artifact
    out_path = PROJECT_ROOT / "scratch" / "phase4_test3_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 70)
    print(f"FINAL RESULT: {'SUCCESS - ALL CRITERIA MET' if report['all_criteria_met'] else 'FAILED'}")
    print(f"FINAL STATE: {report['final_state']}")
    print("=" * 70)
    return report


if __name__ == "__main__":
    result = asyncio.run(run_test_3())
    sys.exit(0 if result.get("all_criteria_met") else 1)
