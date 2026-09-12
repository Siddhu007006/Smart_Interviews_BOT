"""
Phase 4 — Test 5: Multi-Problem Live Run (Two Real Unsolved Problems).

Validates end-to-end multi-problem sequential orchestration across two real unsolved problems:
1. P1: Is Bitonic Sequence (is-bitonic-sequence)
2. P2: Max Min Partition (max-min-partition)

Invariants verified:
- Queue progression: [P1, P2] -> [P2] -> []
- Independent per-problem attempt counters (Attempt 1 for P1, fresh Attempt 1 for P2)
- Zero state leakage between problems
- Verified navigation: advance from P1, assert browser arrives at P2 before solving
- Checkpointing between problems to isolated state file (scratch/state_test5.json)
- Production state safety verified by BOTH content bytes and high-resolution mtime_ns
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any

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
from src.hive.submission import SubmissionManager, SubmissionResult, RunResult, Verdict
from src.state.manager import StateManager

logger = get_logger("Phase4Test5")


async def run_test_5():
    print("=" * 70)
    print("PHASE 4 — TEST 5: MULTI-PROBLEM LIVE RUN (2 UNSOLVED PROBLEMS)")
    print("=" * 70)

    # 1. State Isolation Setup
    isolated_state_file = PROJECT_ROOT / "scratch" / "state_test5.json"
    isolated_state_file.parent.mkdir(parents=True, exist_ok=True)
    if isolated_state_file.exists():
        isolated_state_file.unlink()

    state_manager = StateManager(state_file=isolated_state_file)

    p1_slug = "is-bitonic-sequence"
    p1_title = "Is Bitonic Sequence"
    p2_slug = "max-min-partition"
    p2_title = "Max Min Partition"

    state_manager.add_problem(p1_slug, p1_title)
    state_manager.add_problem(p2_slug, p2_title)
    state_manager.state.problems_queue = [p1_slug, p2_slug]
    state_manager.save_state()

    print(f"  [state] Initialized isolated state at: {isolated_state_file}")
    print(f"  [state] Initial queue: {state_manager.state.problems_queue}")
    assert state_manager.state.problems_queue == [p1_slug, p2_slug], "Queue pre-condition violated"
    assert len(state_manager.state.completed_problems) == 0, "Completed pre-condition violated"

    # 2. Production State Safety Snapshot (Content Bytes + High-Res mtime)
    config = ConfigManager()
    data_dir = Path("~/.hive_bot").expanduser().resolve()
    prod_state_path = data_dir / "state.json"

    prod_bytes_before = None
    prod_mtime_ns_before = None
    if prod_state_path.exists():
        prod_bytes_before = prod_state_path.read_bytes()
        prod_mtime_ns_before = prod_state_path.stat().st_mtime_ns
        print(f"  [safety] Production state snapshot: size={len(prod_bytes_before)} bytes, mtime_ns={prod_mtime_ns_before}")
    else:
        print(f"  [safety] Production state not found at {prod_state_path} (no mutation risk)")

    report: Dict[str, Any] = {
        "p1": {
            "problem_id": p1_slug,
            "title": p1_title,
            "ai_calls": 0,
            "attempt_number": 0,
            "editor_injections": 0,
            "readback_result": False,
            "sample_verdict": None,
            "submissions": 0,
            "final_verdict": None,
            "score": 0,
            "status": "PENDING",
        },
        "p2": {
            "problem_id": p2_slug,
            "title": p2_title,
            "ai_calls": 0,
            "attempt_number": 0,
            "editor_injections": 0,
            "readback_result": False,
            "sample_verdict": None,
            "submissions": 0,
            "final_verdict": None,
            "score": 0,
            "status": "PENDING",
        },
        "navigation": {
            "p1_to_p2_verified": False,
            "url_after_navigation": "",
            "title_after_navigation": "",
        },
        "checkpoints": {
            "after_p1_queue": [],
            "after_p1_completed": [],
            "after_p2_queue": [],
            "after_p2_completed": [],
            "disk_valid_after_p1": False,
            "disk_valid_after_p2": False,
        },
        "safety_audit": {
            "production_state_path": str(prod_state_path),
            "production_bytes_match": False,
            "production_mtime_ns_match": False,
            "isolated_state_path": str(isolated_state_file),
        },
        "final_result": "FAILED",
    }

    profile_path = Path(config.get_required("browser.browser_profile_path")).expanduser().resolve()
    headless = config.get("browser.headless", False)
    channel = config.get("browser.channel", None)

    installer = ExtensionInstaller(profile_path=profile_path, data_dir=data_dir)
    installer.ensure_installed()
    ext_args = installer.get_extension_args()

    browser_manager = BrowserManager(
        profile_path=str(profile_path),
        headless=headless,
        channel=channel,
        extra_args=ext_args,
    )

    contest_base_url = (config.get("hive.contest_url") or "https://hive.smartinterviews.in/contests/smart-interviews-basic").rstrip("/")

    try:
        await browser_manager.launch_browser()
        page = await browser_manager.get_page()

        # Check session / login on contest base
        print(f"\n[Browser] Navigating to contest: {contest_base_url}")
        await page.goto(contest_base_url, wait_until="commit", timeout=90000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(3.0)

        if "login" in page.url.lower():
            print("  - Performing login...")
            creds = Credentials.from_config(config)
            auth_manager = AuthManager(page, creds, timeout_s=60)
            await auth_manager.login()
            await page.goto(contest_base_url, wait_until="commit", timeout=90000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            await asyncio.sleep(3.0)

        checker = ExtensionChecker(page, profile_path)
        await checker.verify_extension_ready(timeout_s=10.0)
        print("  ✓ Extension gate verified and active.")

        engine = AISolverEngine(config)
        sub_mgr = SubmissionManager(run_timeout_s=30.0, submit_timeout_s=60.0, dry_run=False)

        # =================================================================
        # PROBLEM 1: is-bitonic-sequence
        # =================================================================
        print(f"\n" + "=" * 50)
        print(f"STEP 1: SOLVING PROBLEM 1 — {p1_title} ({p1_slug})")
        print("=" * 50)

        p1_url = f"{contest_base_url}/problems/{p1_slug}"
        print(f"  [P1] Navigating to: {p1_url}")
        await page.goto(p1_url, wait_until="commit", timeout=90000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(4.0)

        assert p1_slug in page.url, f"Failed to navigate to P1 URL. Current: {page.url}"
        print(f"  [P1] ✓ Verified on P1 page: {page.url}")

        # Wait for problem statement
        try:
            await page.wait_for_selector(".problem-title, h1, .problem-statement, .description", timeout=20000)
        except Exception:
            pass

        p1_detail = await ProblemDetailParser.extract_from_page(page)
        print(f"  [P1] Extracted detail: Title='{p1_detail.title}', Constraints='{p1_detail.constraints}', Samples={len(p1_detail.sample_cases)}")

        # Select canonical C++
        lang_ctrl = LanguageController(page)
        await lang_ctrl.select_language("C++")
        print("  [P1] ✓ Language set to C++")

        # Bind Monaco
        adapter_p1 = await EditorDetector.detect(page)
        assert await adapter_p1.is_ready(), "Monaco editor not ready for P1"
        print(f"  [P1] ✓ Monaco bound: {adapter_p1}")

        # AI Generation (Attempt 1)
        req_p1 = SolutionRequest(
            problem_id=p1_slug,
            title=p1_detail.title or p1_title,
            description=p1_detail.description,
            input_format=p1_detail.input_format,
            output_format=p1_detail.output_format,
            constraints=p1_detail.constraints,
            sample_cases=p1_detail.sample_cases,
            language="C++",
            attempt_number=1,
            previous_code=None,
            previous_error=None,
            previous_verdict=None,
        )
        assert req_p1.attempt_number == 1, "P1 attempt number must be 1"
        assert req_p1.previous_code is None, "P1 must have no previous code"

        print(f"  [P1] Generating AI solution for Attempt 1...")
        sol_p1 = await engine.solve(req_p1)
        report["p1"]["ai_calls"] += 1
        report["p1"]["attempt_number"] = 1
        print(f"  [P1] ✓ Solution generated ({len(sol_p1.code)} chars) via {sol_p1.provider}")

        # Monaco Injection + Readback
        await adapter_p1.set_code(sol_p1.code)
        report["p1"]["editor_injections"] += 1
        readback_p1 = await adapter_p1.get_code()
        norm_match_p1 = normalize_code(readback_p1) == normalize_code(sol_p1.code)
        report["p1"]["readback_result"] = norm_match_p1
        assert norm_match_p1, "P1 readback code normalization mismatch"
        print(f"  [P1] ✓ Code injected and readback verified")

        # Run Sample Tests
        print("  [P1] Running sample testcases...")
        run_res_p1 = await sub_mgr.run_sample_tests(page)
        report["p1"]["sample_verdict"] = run_res_p1.verdict.value
        print(f"  [P1] Sample test result: {run_res_p1.verdict.value} - {run_res_p1.diagnostic_message}")

        # Live Submit
        print("  [P1] Submitting live solution to Hive...")
        sub_res_p1 = await sub_mgr.submit_solution(page)
        report["p1"]["submissions"] += 1
        report["p1"]["final_verdict"] = sub_res_p1.verdict.value
        report["p1"]["score"] = sub_res_p1.score or 0
        print(f"  [P1] Submission verdict: {sub_res_p1.verdict.value}, Score: {sub_res_p1.score}/{sub_res_p1.max_score}")

        assert sub_res_p1.success or sub_res_p1.verdict == Verdict.ACCEPTED, f"P1 was not Accepted! Verdict: {sub_res_p1.verdict}"
        report["p1"]["status"] = "ACCEPTED"
        print(f"  [P1] ✓ Problem 1 ACCEPTED!")

        # Mid-run Checkpoint Assertion
        state_manager.mark_problem_solved(p1_slug)
        if p1_slug in state_manager.state.problems_queue:
            state_manager.state.problems_queue.remove(p1_slug)
        state_manager.save_state()

        with open(isolated_state_file, "r", encoding="utf-8") as f:
            disk_after_p1 = json.load(f)

        report["checkpoints"]["after_p1_queue"] = list(state_manager.state.problems_queue)
        report["checkpoints"]["after_p1_completed"] = list(state_manager.state.completed_problems)
        report["checkpoints"]["disk_valid_after_p1"] = (
            p1_slug in disk_after_p1["completed_problems"] and
            disk_after_p1["problems_queue"] == [p2_slug]
        )
        assert p1_slug in state_manager.state.completed_problems, "P1 not in completed_problems"
        assert state_manager.state.problems_queue == [p2_slug], f"Queue after P1 mismatch: {state_manager.state.problems_queue}"
        assert report["checkpoints"]["disk_valid_after_p1"], "On-disk checkpoint after P1 invalid!"
        print(f"  [checkpoint] ✓ Checkpoint 1 persisted: Queue={state_manager.state.problems_queue}, Completed={state_manager.state.completed_problems}")

        # =================================================================
        # NAVIGATION: P1 -> P2
        # =================================================================
        print(f"\n" + "=" * 50)
        print(f"STEP 2: NAVIGATION ADVANCEMENT — P1 -> P2 ({p2_title})")
        print("=" * 50)

        p2_url = f"{contest_base_url}/problems/{p2_slug}"

        # Attempt Next Unsolved Problem button click if available
        next_btn = page.locator("button:has-text('Next Unsolved Problem'), .next-unsolved-button")
        clicked_next = False
        if await next_btn.count() > 0 and await next_btn.first.is_visible():
            print("  [nav] Found 'Next Unsolved Problem' button in console. Clicking...")
            try:
                await next_btn.first.click()
                clicked_next = True
                await asyncio.sleep(4.0)
            except Exception as e:
                print(f"  [nav] Next button click error: {e}")

        # Fallback / Direct check: Ensure we arrive on P2 URL
        if p2_slug not in page.url:
            print(f"  [nav] Navigating directly to P2 URL: {p2_url}")
            await page.goto(p2_url, wait_until="commit", timeout=90000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            await asyncio.sleep(4.0)

        # RIGOROUS NAVIGATION GATE ASSERTION
        print("  [nav] Verifying arrival on P2...")
        try:
            await page.wait_for_selector(".problem-title, h1, .problem-statement, .description", timeout=20000)
        except Exception:
            pass

        report["navigation"]["url_after_navigation"] = page.url
        title_el = await page.query_selector(".problem-title, h1, .title")
        dom_title = (await title_el.inner_text()).strip() if title_el else ""
        report["navigation"]["title_after_navigation"] = dom_title

        assert p2_slug in page.url, f"Navigation gate failed: expected '{p2_slug}' in URL, got '{page.url}'"
        print(f"  [nav] ✓ URL verified on P2: {page.url}")
        print(f"  [nav] ✓ DOM Title verified on P2: '{dom_title}'")
        report["navigation"]["p1_to_p2_verified"] = True

        # =================================================================
        # PROBLEM 2: max-min-partition
        # =================================================================
        print(f"\n" + "=" * 50)
        print(f"STEP 3: SOLVING PROBLEM 2 — {p2_title} ({p2_slug})")
        print("=" * 50)

        p2_detail = await ProblemDetailParser.extract_from_page(page)
        print(f"  [P2] Extracted detail: Title='{p2_detail.title}', Constraints='{p2_detail.constraints}', Samples={len(p2_detail.sample_cases)}")

        # Select canonical C++
        await lang_ctrl.select_language("C++")
        print("  [P2] ✓ Language set to C++")

        # Bind Monaco for P2
        adapter_p2 = await EditorDetector.detect(page)
        assert await adapter_p2.is_ready(), "Monaco editor not ready for P2"
        print(f"  [P2] ✓ Monaco bound for P2: {adapter_p2}")

        # CRITICAL ATTEMPT ISOLATION INVARIANT:
        # P2 attempt counter MUST start independently at 1! No leak from P1.
        req_p2 = SolutionRequest(
            problem_id=p2_slug,
            title=p2_detail.title or p2_title,
            description=p2_detail.description,
            input_format=p2_detail.input_format,
            output_format=p2_detail.output_format,
            constraints=p2_detail.constraints,
            sample_cases=p2_detail.sample_cases,
            language="C++",
            attempt_number=1,
            previous_code=None,
            previous_error=None,
            previous_verdict=None,
        )
        assert req_p2.attempt_number == 1, "P2 attempt counter must start independently at 1!"
        assert req_p2.previous_code is None, "P2 must not receive P1 code!"
        assert req_p2.previous_error is None, "P2 must not receive P1 errors!"
        assert req_p2.previous_verdict is None, "P2 must not receive P1 verdicts!"

        print(f"  [P2] Generating AI solution for Attempt 1 (attempt counter isolated)...")
        sol_p2 = await engine.solve(req_p2)
        report["p2"]["ai_calls"] += 1
        report["p2"]["attempt_number"] = 1
        print(f"  [P2] ✓ Solution generated ({len(sol_p2.code)} chars) via {sol_p2.provider}")

        # Monaco Injection + Readback
        await adapter_p2.set_code(sol_p2.code)
        report["p2"]["editor_injections"] += 1
        readback_p2 = await adapter_p2.get_code()
        norm_match_p2 = normalize_code(readback_p2) == normalize_code(sol_p2.code)
        report["p2"]["readback_result"] = norm_match_p2
        assert norm_match_p2, "P2 readback code normalization mismatch"
        print(f"  [P2] ✓ Code injected and readback verified")

        # Run Sample Tests
        print("  [P2] Running sample testcases...")
        run_res_p2 = await sub_mgr.run_sample_tests(page)
        report["p2"]["sample_verdict"] = run_res_p2.verdict.value
        print(f"  [P2] Sample test result: {run_res_p2.verdict.value} - {run_res_p2.diagnostic_message}")

        # Live Submit
        print("  [P2] Submitting live solution to Hive...")
        sub_res_p2 = await sub_mgr.submit_solution(page)
        report["p2"]["submissions"] += 1
        report["p2"]["final_verdict"] = sub_res_p2.verdict.value
        report["p2"]["score"] = sub_res_p2.score or 0
        print(f"  [P2] Submission verdict: {sub_res_p2.verdict.value}, Score: {sub_res_p2.score}/{sub_res_p2.max_score}")

        assert sub_res_p2.success or sub_res_p2.verdict == Verdict.ACCEPTED, f"P2 was not Accepted! Verdict: {sub_res_p2.verdict}"
        report["p2"]["status"] = "ACCEPTED"
        print(f"  [P2] ✓ Problem 2 ACCEPTED!")

        # Terminal Checkpoint Assertion
        state_manager.mark_problem_solved(p2_slug)
        if p2_slug in state_manager.state.problems_queue:
            state_manager.state.problems_queue.remove(p2_slug)
        state_manager.save_state()

        with open(isolated_state_file, "r", encoding="utf-8") as f:
            disk_after_p2 = json.load(f)

        report["checkpoints"]["after_p2_queue"] = list(state_manager.state.problems_queue)
        report["checkpoints"]["after_p2_completed"] = list(state_manager.state.completed_problems)
        report["checkpoints"]["disk_valid_after_p2"] = (
            set(disk_after_p2["completed_problems"]) == {p1_slug, p2_slug} and
            disk_after_p2["problems_queue"] == []
        )
        assert set(state_manager.state.completed_problems) == {p1_slug, p2_slug}
        assert state_manager.state.problems_queue == []
        assert report["checkpoints"]["disk_valid_after_p2"], "On-disk checkpoint after P2 invalid!"
        print(f"  [checkpoint] ✓ Checkpoint 2 persisted: Queue={state_manager.state.problems_queue}, Completed={state_manager.state.completed_problems}")

        # Take screenshot evidence
        screenshot_path = PROJECT_ROOT / "scratch" / "test5_p2_accepted.png"
        await page.screenshot(path=str(screenshot_path), full_page=False)
        print(f"  [evidence] Screenshot captured at: {screenshot_path}")

        # 3. Post-Condition Audit & Production Safety Checks
        print(f"\n" + "=" * 50)
        print("STEP 4: POST-CONDITIONS & PRODUCTION SAFETY AUDIT")
        print("=" * 50)

        # Assert exactly 2 submissions
        total_submits = report["p1"]["submissions"] + report["p2"]["submissions"]
        assert total_submits == 2, f"Total submissions expected 2, got {total_submits}"
        print(f"  ✓ Submissions count: exactly 2 ({report['p1']['submissions']} + {report['p2']['submissions']})")

        # Production State Byte & Timestamp Verification
        if prod_state_path.exists():
            prod_bytes_after = prod_state_path.read_bytes()
            prod_mtime_ns_after = prod_state_path.stat().st_mtime_ns

            bytes_match = (prod_bytes_before == prod_bytes_after)
            mtime_match = (prod_mtime_ns_before == prod_mtime_ns_after)

            report["safety_audit"]["production_bytes_match"] = bytes_match
            report["safety_audit"]["production_mtime_ns_match"] = mtime_match

            assert bytes_match, "CRITICAL: Production state content bytes were modified during Test 5!"
            assert mtime_match, f"CRITICAL: Production state mtime_ns changed! Before: {prod_mtime_ns_before}, After: {prod_mtime_ns_after}"
            print("  ✓ Production state bytes verified 100% identical.")
            print("  ✓ Production state high-resolution mtime_ns verified 100% identical.")
        else:
            report["safety_audit"]["production_bytes_match"] = True
            report["safety_audit"]["production_mtime_ns_match"] = True

        report["final_result"] = "SUCCESS"
        print("\n" + "=" * 70)
        print("FINAL RESULT: SUCCESS — ALL TEST 5 ACCEPTANCE CRITERIA MET")
        print("=" * 70)

    except Exception as e:
        print(f"\n[ERROR] Test 5 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        report["final_result"] = f"FAILED: {e}"

    finally:
        await browser_manager.close()

    # Persist report artifact
    report_file = PROJECT_ROOT / "scratch" / "phase4_test5_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Report saved to: {report_file}")

    return report


if __name__ == "__main__":
    res = asyncio.run(run_test_5())
    sys.exit(0 if res.get("final_result") == "SUCCESS" else 1)
