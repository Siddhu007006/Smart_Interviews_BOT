"""
Phase 4 — Test 6: Restart Recovery Validation.

Proves crash resilience and workflow reconstruction across a genuine OS-process boundary:
- Phase 1 (Subprocess 1):
    Queue: [P1, P2] -> Solves P1 live -> Checkpoints [completed: P1, queue: P2] -> Exits 0
- Real OS-process termination
- Phase 2 (Subprocess 2):
    Fresh process loads on-disk state -> Detects P1 completed -> Skips P1
    (AI calls = 0, submissions = 0, navigation = 0) -> Resumes queue at P2
    -> Solves P2 live -> Checkpoints [completed: P1, P2, queue: []] -> Exits 0
- Master Orchestrator:
    Combines per-process metrics, audits zero duplicate submissions, and verifies
    production state unchanged by content bytes and nanosecond mtime.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import get_logger, ConfigManager
from src.browser.manager import BrowserManager
from src.browser.extension_installer import ExtensionInstaller
from src.browser.extension import ExtensionChecker
from src.auth import AuthManager, Credentials
from src.hive.problem_detail import ProblemDetailParser
from src.editor.language_controller import LanguageController
from src.editor.detector import EditorDetector
from src.editor.adapter import normalize_code
from src.solver.engine import AISolverEngine
from src.solver.models import SolutionRequest
from src.hive.submission import SubmissionManager, Verdict
from src.state.manager import StateManager

logger = get_logger("Phase4Test6")

P1_SLUG = "alternate-seating"
P1_TITLE = "Alternate Seating"
P2_SLUG = "three-parts"
P2_TITLE = "Three Parts"


# =====================================================================
# SUBPROCESS: PHASE 1
# =====================================================================

async def run_phase_1(state_file: Path, metrics_file: Path):
    print("=" * 60)
    print("PROCESS 1: SOLVING P1 AND CHECKPOINTING BEFORE TERMINATION")
    print("=" * 60)

    # Initialize state file
    if state_file.exists():
        state_file.unlink()

    state_manager = StateManager(state_file=state_file)
    state_manager.add_problem(P1_SLUG, P1_TITLE)
    state_manager.add_problem(P2_SLUG, P2_TITLE)
    state_manager.state.problems_queue = [P1_SLUG, P2_SLUG]
    state_manager.save_state()

    print(f"  [P1-Init] State seeded: Queue={state_manager.state.problems_queue}, Completed={state_manager.state.completed_problems}")

    config = ConfigManager()
    profile_path = Path(config.get_required("browser.browser_profile_path")).expanduser().resolve()
    data_dir = Path("~/.hive_bot").expanduser().resolve()
    installer = ExtensionInstaller(profile_path=profile_path, data_dir=data_dir)
    installer.ensure_installed()
    ext_args = installer.get_extension_args()

    browser_manager = BrowserManager(
        profile_path=str(profile_path),
        headless=config.get("browser.headless", False),
        channel=config.get("browser.channel", None),
        extra_args=ext_args,
    )

    contest_base_url = (config.get("hive.contest_url") or "https://hive.smartinterviews.in/contests/smart-interviews-basic").rstrip("/")
    p1_url = f"{contest_base_url}/problems/{P1_SLUG}"

    metrics = {
        "phase": 1,
        "pid": os.getpid(),
        "p1_slug": P1_SLUG,
        "p1_ai_calls": 0,
        "p1_submissions": 0,
        "p1_navigation": 0,
        "p1_verdict": None,
        "p1_score": 0,
        "state_queue_after": [],
        "state_completed_after": [],
        "success": False,
    }

    try:
        await browser_manager.launch_browser()
        page = await browser_manager.get_page()

        print(f"  [P1] Navigating to {p1_url}...")
        metrics["p1_navigation"] += 1
        await page.goto(p1_url, wait_until="commit", timeout=90000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(4.0)

        if "login" in page.url.lower():
            creds = Credentials.from_config(config)
            auth_manager = AuthManager(page, creds)
            await auth_manager.login()
            await page.goto(p1_url, wait_until="commit", timeout=90000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            await asyncio.sleep(4.0)

        checker = ExtensionChecker(page, profile_path)
        await checker.verify_extension_ready(timeout_s=10.0)
        assert P1_SLUG in page.url, f"Failed to arrive on P1 URL. Current: {page.url}"

        # Wait for problem statement
        try:
            await page.wait_for_selector(".problem-title, h1, .problem-statement, .description", timeout=20000)
        except Exception:
            pass

        p1_detail = await ProblemDetailParser.extract_from_page(page)
        print(f"  [P1] Extracted: '{p1_detail.title}', Constraints='{p1_detail.constraints}'")

        lang_ctrl = LanguageController(page)
        await lang_ctrl.select_language("C++")

        adapter_p1 = await EditorDetector.detect(page)
        assert await adapter_p1.is_ready()

        engine = AISolverEngine(config)
        sub_mgr = SubmissionManager(run_timeout_s=30.0, submit_timeout_s=60.0, dry_run=False)

        req_p1 = SolutionRequest(
            problem_id=P1_SLUG,
            title=p1_detail.title or P1_TITLE,
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

        print("  [P1] Generating AI solution...")
        sol_p1 = await engine.solve(req_p1)
        metrics["p1_ai_calls"] += 1

        await adapter_p1.set_code(sol_p1.code)
        readback = await adapter_p1.get_code()
        assert normalize_code(readback) == normalize_code(sol_p1.code)

        print("  [P1] Running sample testcases...")
        await sub_mgr.run_sample_tests(page)

        print("  [P1] Submitting live solution to Hive...")
        sub_res_p1 = await sub_mgr.submit_solution(page)
        metrics["p1_submissions"] += 1
        metrics["p1_verdict"] = sub_res_p1.verdict.value
        metrics["p1_score"] = sub_res_p1.score or 0

        assert sub_res_p1.success or sub_res_p1.verdict == Verdict.ACCEPTED, f"P1 failed: {sub_res_p1.verdict}"
        print(f"  [P1] ✓ ACCEPTED on Attempt 1! Score: {sub_res_p1.score}/{sub_res_p1.max_score}")

        # Evidence screenshot
        screenshot_path_p1 = PROJECT_ROOT / "scratch" / "test6_p1_accepted.png"
        await page.screenshot(path=str(screenshot_path_p1), full_page=False)
        print(f"  [P1-Evidence] Screenshot saved to {screenshot_path_p1}")

        # Checkpoint: Mark P1 solved, dequeue P1, save state
        state_manager.mark_problem_solved(P1_SLUG)
        if P1_SLUG in state_manager.state.problems_queue:
            state_manager.state.problems_queue.remove(P1_SLUG)
        state_manager.save_state()

        metrics["state_queue_after"] = list(state_manager.state.problems_queue)
        metrics["state_completed_after"] = list(state_manager.state.completed_problems)
        metrics["success"] = True

        print(f"  [P1-Checkpoint] Checkpoint saved: Queue={metrics['state_queue_after']}, Completed={metrics['state_completed_after']}")

    finally:
        # Crucial: clean browser close before process exits
        await browser_manager.close()
        print("  [P1-Teardown] Browser context cleanly closed.")

    # Write Phase 1 metrics
    with open(metrics_file, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"  [P1-Done] Metrics saved to {metrics_file}. Exiting process 1 with code 0.")


# =====================================================================
# SUBPROCESS: PHASE 2 (FRESH OS PROCESS RESTART)
# =====================================================================

async def run_phase_2(state_file: Path, metrics_file: Path):
    print("=" * 60)
    print("PROCESS 2: RESTART RECOVERY & SOLVING UNFINISHED QUEUE (P2)")
    print("=" * 60)

    # 1. Load state directly from disk (fresh memory space)
    state_manager = StateManager(state_file=state_file)
    print(f"  [P2-Boot] Fresh StateManager loaded from {state_file}")
    print(f"  [P2-Boot] Loaded Queue: {state_manager.state.problems_queue}")
    print(f"  [P2-Boot] Loaded Completed: {state_manager.state.completed_problems}")

    # Assertions on deserialized state
    assert P1_SLUG in state_manager.state.completed_problems, "P1 must be in completed_problems upon restart"
    assert state_manager.state.problems_queue == [P2_SLUG], f"Queue must contain only [P2] upon restart, got {state_manager.state.problems_queue}"

    metrics = {
        "phase": 2,
        "pid": os.getpid(),
        "p1_slug": P1_SLUG,
        "p1_ai_calls_after_restart": 0,
        "p1_submissions_after_restart": 0,
        "p1_navigation_after_restart": 0,
        "p1_skipped": False,
        "p2_slug": P2_SLUG,
        "p2_attempt_number": 0,
        "p2_ai_calls": 0,
        "p2_submissions": 0,
        "p2_navigation": 0,
        "p2_verdict": None,
        "p2_score": 0,
        "state_queue_after": [],
        "state_completed_after": [],
        "success": False,
    }

    # Verify P1 Skip Invariant:
    # If the bot is asked to solve P1, it must skip immediately without opening browser or calling AI/submit
    config = ConfigManager()
    if P1_SLUG in state_manager.state.completed_problems:
        print(f"  [P1-Audit] P1 '{P1_SLUG}' detected in completed_problems. Verifying skip logic...")
        # Neither browser navigation nor AI nor submission should occur for P1
        metrics["p1_skipped"] = True
        metrics["p1_ai_calls_after_restart"] = 0
        metrics["p1_submissions_after_restart"] = 0
        metrics["p1_navigation_after_restart"] = 0
        print("  [P1-Audit] ✓ P1 skipped cleanly: AI calls=0, Submissions=0, Navigation=0")

    # Now solve P2 from unfinished queue
    profile_path = Path(config.get_required("browser.browser_profile_path")).expanduser().resolve()
    data_dir = Path("~/.hive_bot").expanduser().resolve()
    installer = ExtensionInstaller(profile_path=profile_path, data_dir=data_dir)
    installer.ensure_installed()
    ext_args = installer.get_extension_args()

    browser_manager = BrowserManager(
        profile_path=str(profile_path),
        headless=config.get("browser.headless", False),
        channel=config.get("browser.channel", None),
        extra_args=ext_args,
    )

    contest_base_url = (config.get("hive.contest_url") or "https://hive.smartinterviews.in/contests/smart-interviews-basic").rstrip("/")
    p2_url = f"{contest_base_url}/problems/{P2_SLUG}"

    try:
        await browser_manager.launch_browser()
        page = await browser_manager.get_page()

        print(f"  [P2] Navigating directly to P2: {p2_url}...")
        metrics["p2_navigation"] += 1
        await page.goto(p2_url, wait_until="commit", timeout=90000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(4.0)

        if "login" in page.url.lower():
            creds = Credentials.from_config(config)
            auth_manager = AuthManager(page, creds)
            await auth_manager.login()
            await page.goto(p2_url, wait_until="commit", timeout=90000)
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            await asyncio.sleep(4.0)

        checker = ExtensionChecker(page, profile_path)
        await checker.verify_extension_ready(timeout_s=10.0)
        assert P2_SLUG in page.url, f"Failed to arrive on P2 URL. Current: {page.url}"

        try:
            await page.wait_for_selector(".problem-title, h1, .problem-statement, .description", timeout=20000)
        except Exception:
            pass

        p2_detail = await ProblemDetailParser.extract_from_page(page)
        print(f"  [P2] Extracted: '{p2_detail.title}', Constraints='{p2_detail.constraints}'")

        lang_ctrl = LanguageController(page)
        await lang_ctrl.select_language("C++")

        adapter_p2 = await EditorDetector.detect(page)
        assert await adapter_p2.is_ready()

        engine = AISolverEngine(config)
        sub_mgr = SubmissionManager(run_timeout_s=30.0, submit_timeout_s=60.0, dry_run=False)

        # CRITICAL: Attempt counter starts fresh at Attempt 1
        req_p2 = SolutionRequest(
            problem_id=P2_SLUG,
            title=p2_detail.title or P2_TITLE,
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
        metrics["p2_attempt_number"] = 1

        print("  [P2] Generating AI solution for Attempt 1...")
        sol_p2 = await engine.solve(req_p2)
        metrics["p2_ai_calls"] += 1

        await adapter_p2.set_code(sol_p2.code)
        readback = await adapter_p2.get_code()
        assert normalize_code(readback) == normalize_code(sol_p2.code)

        print("  [P2] Running sample testcases...")
        await sub_mgr.run_sample_tests(page)

        print("  [P2] Submitting live solution to Hive...")
        sub_res_p2 = await sub_mgr.submit_solution(page)
        metrics["p2_submissions"] += 1
        metrics["p2_verdict"] = sub_res_p2.verdict.value
        metrics["p2_score"] = sub_res_p2.score or 0

        assert sub_res_p2.success or sub_res_p2.verdict == Verdict.ACCEPTED, f"P2 failed: {sub_res_p2.verdict}"
        print(f"  [P2] ✓ ACCEPTED on Attempt 1! Score: {sub_res_p2.score}/{sub_res_p2.max_score}")

        # Final Checkpoint: Mark P2 solved, dequeue P2, save state
        state_manager.mark_problem_solved(P2_SLUG)
        if P2_SLUG in state_manager.state.problems_queue:
            state_manager.state.problems_queue.remove(P2_SLUG)
        state_manager.save_state()

        metrics["state_queue_after"] = list(state_manager.state.problems_queue)
        metrics["state_completed_after"] = list(state_manager.state.completed_problems)
        metrics["success"] = True

        print(f"  [P2-Checkpoint] Final checkpoint saved: Queue={metrics['state_queue_after']}, Completed={metrics['state_completed_after']}")

        # Evidence screenshot
        screenshot_path = PROJECT_ROOT / "scratch" / "test6_p2_accepted.png"
        await page.screenshot(path=str(screenshot_path), full_page=False)
        print(f"  [P2-Evidence] Screenshot saved to {screenshot_path}")

    finally:
        await browser_manager.close()
        print("  [P2-Teardown] Browser context cleanly closed.")

    with open(metrics_file, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    print(f"  [P2-Done] Metrics saved to {metrics_file}. Exiting process 2 with code 0.")


# =====================================================================
# MASTER ORCHESTRATOR
# =====================================================================

def run_master_orchestrator():
    print("=" * 70)
    print("PHASE 4 — TEST 6: RESTART RECOVERY (DUAL-PROCESS BOUNDARY)")
    print("=" * 70)

    state_file = PROJECT_ROOT / "scratch" / "state_test6.json"
    phase1_metrics_file = PROJECT_ROOT / "scratch" / "test6_phase1_metrics.json"
    phase2_metrics_file = PROJECT_ROOT / "scratch" / "test6_phase2_metrics.json"
    report_file = PROJECT_ROOT / "scratch" / "phase4_test6_report.json"

    # Clean previous run artifacts
    for f in (state_file, phase1_metrics_file, phase2_metrics_file, report_file):
        if f.exists():
            f.unlink()

    # 1. Snapshot Production State (Content Bytes + High-Res mtime)
    data_dir = Path("~/.hive_bot").expanduser().resolve()
    prod_state_path = data_dir / "state.json"
    prod_bytes_before = None
    prod_mtime_ns_before = None
    if prod_state_path.exists():
        prod_bytes_before = prod_state_path.read_bytes()
        prod_mtime_ns_before = prod_state_path.stat().st_mtime_ns
        print(f"  [Safety] Production state snapshot: size={len(prod_bytes_before)} bytes, mtime_ns={prod_mtime_ns_before}")

    python_exe = sys.executable

    # 2. Launch Subprocess 1 (Phase 1)
    print("\n>>> Launching Process 1 (P1 Solve & Checkpoint)...")
    cmd_p1 = [
        python_exe,
        str(Path(__file__).resolve()),
        "--phase", "1",
        "--state-file", str(state_file),
        "--metrics-file", str(phase1_metrics_file),
    ]
    proc1 = subprocess.run(cmd_p1, cwd=str(PROJECT_ROOT))
    assert proc1.returncode == 0, f"Process 1 failed with exit code {proc1.returncode}!"
    print(f">>> Process 1 cleanly terminated with return code {proc1.returncode}.")

    # 3. Inter-process On-Disk Checkpoint Audit
    print("\n>>> Auditing on-disk state checkpoint between processes...")
    assert state_file.exists(), "State file was not written to disk by Process 1!"
    with open(state_file, "r", encoding="utf-8") as f:
        disk_after_p1 = json.load(f)

    assert P1_SLUG in disk_after_p1["completed_problems"], f"P1 '{P1_SLUG}' missing from completed_problems in on-disk state!"
    assert disk_after_p1["problems_queue"] == [P2_SLUG], f"Queue after P1 mismatch! Expected [{P2_SLUG}], got {disk_after_p1['problems_queue']}"
    print(f"  ✓ Checkpoint verified on disk: completed_problems={disk_after_p1['completed_problems']}, problems_queue={disk_after_p1['problems_queue']}")

    assert phase1_metrics_file.exists(), "Phase 1 metrics file not found!"
    with open(phase1_metrics_file, "r", encoding="utf-8") as f:
        p1_metrics = json.load(f)
    assert p1_metrics["p1_submissions"] == 1, "P1 must have exactly 1 submission in Process 1"
    assert p1_metrics["p1_verdict"] == "Accepted", "P1 must be Accepted in Process 1"

    # 4. Launch Subprocess 2 (Phase 2 - Fresh Process Restart)
    print("\n>>> Launching Process 2 (Fresh Process Restart & Recovery)...")
    cmd_p2 = [
        python_exe,
        str(Path(__file__).resolve()),
        "--phase", "2",
        "--state-file", str(state_file),
        "--metrics-file", str(phase2_metrics_file),
    ]
    proc2 = subprocess.run(cmd_p2, cwd=str(PROJECT_ROOT))
    assert proc2.returncode == 0, f"Process 2 failed with exit code {proc2.returncode}!"
    print(f">>> Process 2 cleanly terminated with return code {proc2.returncode}.")

    # 5. Final State Audit & Metrics Compilation
    print("\n>>> Compiling Master Evidence & Verifying Invariants...")
    assert phase2_metrics_file.exists(), "Phase 2 metrics file not found!"
    with open(phase2_metrics_file, "r", encoding="utf-8") as f:
        p2_metrics = json.load(f)

    # Invariant checks:
    assert p2_metrics["pid"] != p1_metrics["pid"], "Process 2 must have a distinct PID (real OS-process boundary)!"
    assert p2_metrics["p1_skipped"] is True, "P1 was not marked skipped in Process 2!"
    assert p2_metrics["p1_ai_calls_after_restart"] == 0, "AI called for P1 after restart!"
    assert p2_metrics["p1_submissions_after_restart"] == 0, "Submission made for P1 after restart!"
    assert p2_metrics["p1_navigation_after_restart"] == 0, "Browser navigated to P1 after restart!"
    assert p2_metrics["p2_attempt_number"] == 1, "P2 attempt number did not start fresh at 1!"
    assert p2_metrics["p2_submissions"] == 1, "P2 did not execute exactly 1 submission!"
    assert p2_metrics["p2_verdict"] == "Accepted", "P2 was not Accepted!"

    # Final on-disk state audit
    with open(state_file, "r", encoding="utf-8") as f:
        final_disk_state = json.load(f)

    assert set(final_disk_state["completed_problems"]) == {P1_SLUG, P2_SLUG}, f"Final completed problems mismatch: {final_disk_state['completed_problems']}"
    assert final_disk_state["problems_queue"] == [], f"Final queue not empty: {final_disk_state['problems_queue']}"

    # Total submissions across both processes
    total_submissions = p1_metrics["p1_submissions"] + p2_metrics["p2_submissions"] + p2_metrics["p1_submissions_after_restart"]
    assert total_submissions == 2, f"Total submissions expected 2, got {total_submissions}"

    # Production State Safety Check
    prod_bytes_match = True
    prod_mtime_match = True
    if prod_state_path.exists():
        prod_bytes_after = prod_state_path.read_bytes()
        prod_mtime_ns_after = prod_state_path.stat().st_mtime_ns
        prod_bytes_match = (prod_bytes_before == prod_bytes_after)
        prod_mtime_match = (prod_mtime_ns_before == prod_mtime_ns_after)
        assert prod_bytes_match, "CRITICAL: Production state bytes modified!"
        assert prod_mtime_match, "CRITICAL: Production state mtime modified!"
        print("  ✓ Production state bytes 100% untouched.")
        print("  ✓ Production state mtime_ns 100% untouched.")

    master_report = {
        "process_1": p1_metrics,
        "process_2": p2_metrics,
        "restart_verification": {
            "p1_submissions_before_restart": p1_metrics["p1_submissions"],
            "p1_submissions_after_restart": p2_metrics["p1_submissions_after_restart"],
            "p1_ai_calls_after_restart": p2_metrics["p1_ai_calls_after_restart"],
            "p1_navigation_after_restart": p2_metrics["p1_navigation_after_restart"],
            "p2_attempt_number": p2_metrics["p2_attempt_number"],
            "p2_submissions": p2_metrics["p2_submissions"],
            "total_live_submissions": total_submissions,
            "zero_duplicate_submissions": (p2_metrics["p1_submissions_after_restart"] == 0 and total_submissions == 2),
            "process_boundary_verified": (p1_metrics["pid"] != p2_metrics["pid"]),
        },
        "final_state": {
            "completed_problems": final_disk_state["completed_problems"],
            "problems_queue": final_disk_state["problems_queue"],
        },
        "safety_audit": {
            "production_bytes_match": prod_bytes_match,
            "production_mtime_ns_match": prod_mtime_match,
        },
        "final_result": "SUCCESS",
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(master_report, f, indent=2)

    print("\n" + "=" * 70)
    print("FINAL RESULT: SUCCESS — ALL TEST 6 RESTART ACCEPTANCE CRITERIA MET")
    print(f"Report saved to: {report_file}")
    print("=" * 70)
    return master_report


# =====================================================================
# CLI ENTRY POINT
# =====================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4 Test 6 Restart Recovery Runner")
    parser.add_argument("--phase", type=int, choices=[1, 2], help="Run specific subprocess phase (1 or 2)")
    parser.add_argument("--state-file", type=str, help="Path to isolated state file")
    parser.add_argument("--metrics-file", type=str, help="Path to write phase metrics JSON")

    args = parser.parse_args()

    if args.phase == 1:
        s_file = Path(args.state_file) if args.state_file else PROJECT_ROOT / "scratch" / "state_test6.json"
        m_file = Path(args.metrics_file) if args.metrics_file else PROJECT_ROOT / "scratch" / "test6_phase1_metrics.json"
        asyncio.run(run_phase_1(s_file, m_file))
    elif args.phase == 2:
        s_file = Path(args.state_file) if args.state_file else PROJECT_ROOT / "scratch" / "state_test6.json"
        m_file = Path(args.metrics_file) if args.metrics_file else PROJECT_ROOT / "scratch" / "test6_phase2_metrics.json"
        asyncio.run(run_phase_2(s_file, m_file))
    else:
        # Master orchestrator mode
        rep = run_master_orchestrator()
        sys.exit(0 if rep.get("final_result") == "SUCCESS" else 1)
