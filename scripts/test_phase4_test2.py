"""
Phase 4 — Test 2: One Real Problem, Dry-Run Validation.

Validates the critical integration pipeline on ONE real unsolved problem without submitting:
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
Parse Sample Result
  ↓
STOP (Submit strictly prohibited via dry_run guard)
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
from src.hive.submission import SubmissionManager, RunResult, Verdict

logger = get_logger("Phase4Test2")


async def run_test_2():
    print("=" * 70)
    print("PHASE 4 — TEST 2: ONE REAL PROBLEM, DRY RUN VALIDATION")
    print("=" * 70)

    report = {
        "problem_extraction": {},
        "language_selection": {},
        "editor_binding": {},
        "ai_generation": {},
        "code_injection": {},
        "sample_execution": {},
        "safety_audit": {
            "ai_calls": 0,
            "editor_injections": 0,
            "runs": 0,
            "submits": 0,
            "dry_run_guard_verified": False,
        },
        "final_state": "PENDING",
        "all_criteria_met": False,
    }

    # Explicitly load .env from project root so API keys are available
    from dotenv import load_dotenv
    repo_root = PROJECT_ROOT
    dotenv_path = repo_root / ".env"
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

    # 2. Setup Extension Args & Browser
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

        # 3. Extract Problem Details
        # Wait for Angular to render the problem content (title selector)
        print("  - Waiting for problem DOM to render...")
        try:
            await page.wait_for_selector(".problem-title, h1, .problem-statement, .description", timeout=20000)
        except Exception:
            pass  # Fallback: continue even if selector not found; extractor will report empty
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
            "sample_cases": [sc.to_dict() for sc in problem_detail.sample_cases],
        }

        print(f"  - Problem ID: {problem_detail.problem_id}")
        print(f"  - Title: {problem_detail.title}")
        print(f"  - Statement snippet: {repr(problem_detail.description[:120])}")
        print(f"  - Input Format: {repr(problem_detail.input_format)}")
        print(f"  - Output Format: {repr(problem_detail.output_format)}")
        print(f"  - Constraints: {repr(problem_detail.constraints)}")
        print(f"  - Sample cases count: {len(problem_detail.sample_cases)}")

        # 4. Language Selection & Verification
        print("\n[3] Controlling Editor Language...")
        lang_controller = LanguageController()
        before_lang = await lang_controller.get_current_language(page)
        print(f"  - Language before action: {before_lang}")

        selected_lang = await lang_controller.select_language(page, "C++")
        after_lang = await lang_controller.get_current_language(page)
        print(f"  - Action: select_language('C++') -> returned={selected_lang}")
        print(f"  - Language after action: {after_lang}")

        norm_after = LanguageController.normalize_to_canonical(after_lang)
        report["language_selection"] = {
            "before": before_lang,
            "requested": "C++",
            "after": after_lang,
            "normalized_after": norm_after,
            "verified_match": (norm_after == "C++" or after_lang == "C++"),
        }

        # 5. Detect & Bind Monaco Editor Instance
        print("\n[4] Detecting and Binding Monaco Editor...")
        editor_detector = EditorDetector(page)
        adapter = await editor_detector.detect_and_bind()

        container_found = await page.query_selector("#editor") is not None
        initial_starter_code = await adapter.get_code()

        report["editor_binding"] = {
            "editor_type": type(adapter).__name__,
            "container_selector": "#editor",
            "container_found": container_found,
            "starter_code_present": bool(initial_starter_code.strip()),
            "starter_code_snippet": initial_starter_code[:100] if initial_starter_code else "",
        }
        report["problem_extraction"]["starter_code"] = initial_starter_code[:200] if initial_starter_code else "None"

        print(f"  - Container '#editor' found: {container_found}")
        print(f"  - Bound editor type: {type(adapter).__name__}")
        print(f"  - Initial code snippet: {repr(initial_starter_code[:60])}")

        # 6. AI Solution Generation
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
            language="C++",
            attempt_number=1,
        )

        report["safety_audit"]["ai_calls"] += 1
        sol_response = await engine.solve(sol_request)

        print(f"  - Provider used: {sol_response.provider}")
        print(f"  - Model used: {sol_response.model}")
        print(f"  - Code length: {len(sol_response.code)} chars")
        print(f"  - Generated code preview:\n{'-'*40}\n{sol_response.code[:200]}...\n{'-'*40}")

        # The engine already ran clean_and_validate internally before returning SolutionResponse.
        # Re-run here purely to confirm the returned code still passes (belt-and-suspenders audit).
        try:
            validated_code = SolutionValidator.clean_and_validate(sol_response.code, "C++")
            validator_accepted = bool(validated_code)
        except Exception as ve:
            validated_code = sol_response.code  # engine already validated; use as-is
            validator_accepted = False
            print(f"  [WARN] Post-hoc validator raised: {ve}")

        report["ai_generation"] = {
            "provider": sol_response.provider,
            "model": sol_response.model,
            "code_generated": True,
            "validator_accepted": validator_accepted,
        }

        # 7. Code Injection & Readback Verification
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
        if not readback_match:
            print("  [!] Readback mismatch!")
            print(f"  Expected:\n{norm_expected[:150]}")
            print(f"  Actual:\n{norm_readback[:150]}")

        # 8. Sample Run with Dry-Run Safety Boundary
        print("\n[7] Executing Sample Run (dry_run=True guard active)...")
        sub_mgr = SubmissionManager(run_timeout_s=35.0, submit_timeout_s=45.0, dry_run=True)

        # First, test the safety boundary directly: verify that submit_solution raises SubmissionError
        try:
            await sub_mgr.submit_solution(page)
            print("  [CRITICAL ERROR] Dry-run guard FAILED! submit_solution did not raise!")
            report["safety_audit"]["dry_run_guard_verified"] = False
        except SubmissionError as e:
            print(f"  - Dry-run guard VERIFIED: submit_solution raised {type(e).__name__}: {e}")
            report["safety_audit"]["dry_run_guard_verified"] = True

        # Now execute sample run
        report["safety_audit"]["runs"] += 1
        run_result = await sub_mgr.run_sample_tests(page)

        print(f"  - Sample Run success: {run_result.success}")
        print(f"  - Verdict: {run_result.verdict.value}")
        print(f"  - Sample cases evaluated: {len(run_result.sample_cases)}")
        for i, sc in enumerate(run_result.sample_cases):
            print(f"    Case #{i+1}: passed={sc.passed}, input={repr(sc.input_data)}, actual={repr(sc.actual_output)}, expected={repr(sc.expected_output)}")
        if run_result.diagnostic_message:
            print(f"  - Diagnostic Message:\n{run_result.diagnostic_message[:200]}")

        report["sample_execution"] = {
            "success": run_result.success,
            "verdict": run_result.verdict.value,
            "sample_cases_count": len(run_result.sample_cases),
            "sample_cases": [
                {
                    "passed": sc.passed,
                    "input": sc.input_data,
                    "actual_output": sc.actual_output,
                    "expected_output": sc.expected_output,
                }
                for sc in run_result.sample_cases
            ],
            "diagnostic_message": run_result.diagnostic_message,
            "error_kind": run_result.error_kind.value if run_result.error_kind else None,
        }

        # STOP - No submit
        report["final_state"] = "DRY_RUN_COMPLETE"

        # Overall acceptance criteria check
        report["all_criteria_met"] = (
            bool(report["problem_extraction"].get("title"))
            and report["language_selection"].get("verified_match") is True
            and report["editor_binding"].get("container_found") is True
            and report["ai_generation"].get("validator_accepted") is True
            and report["code_injection"].get("normalized_match") is True
            and report["safety_audit"]["dry_run_guard_verified"] is True
            and report["safety_audit"]["ai_calls"] > 0
            and report["safety_audit"]["editor_injections"] == 1
            and report["safety_audit"]["runs"] == 1
            and report["safety_audit"]["submits"] == 0
            and report["final_state"] == "DRY_RUN_COMPLETE"
            and run_result.is_verdict_determined
        )

    except Exception as e:
        logger.error(f"Test 2 failed with exception: {e}", exc_info=True)
        print(f"\n[ERROR] Test 2 failed: {e}")
        report["final_state"] = "FAILED"
    finally:
        await browser_manager.close()
        print("\n[8] Browser closed cleanly.")

    # Save artifact
    out_path = PROJECT_ROOT / "scratch" / "phase4_test2_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 70)
    print(f"FINAL RESULT: {'SUCCESS - ALL CRITERIA MET' if report['all_criteria_met'] else 'FAILED'}")
    print(f"FINAL STATE: {report['final_state']}")
    print("=" * 70)
    return report


if __name__ == "__main__":
    result = asyncio.run(run_test_2())
    sys.exit(0 if result.get("all_criteria_met") else 1)
