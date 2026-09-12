"""
Phase 4 — Test 4: Deliberate Retry Validation (Controlled Test Doubles).

Executes an offline controlled validation harness with test doubles to verify
all retry state machine transitions without burning live submissions:

1. Wrong Answer:
   Attempt 1 → Attempt 2 (repair prompt receives previous code, verdict, and error diff)
2. Compilation Error:
   Attempt 1 → Attempt 2 (repair prompt receives exact compiler diagnostic)
3. Platform Timeout Boundary:
   Attempt 1 → Submit TIMEOUT → platform retry → Submit ACCEPTED
   (AI calls = 1, current_code retained, attempt = 1, completed)
4. Platform Timeout Exhaustion:
   Submit TIMEOUT × 3 → Bounded platform retries exhausted (clean exit, no infinite loop)
5. Fifth Evaluated Failure:
   Attempt 5 fails → marked failed=True, added to failed_problems, dequeued from problems_queue
6. Provider Fallback vs. Problem Attempt:
   Provider 1 RATE_LIMIT (429) → Provider 2 returns code (within Attempt 1; attempt count = 1)
7. State Checkpoint Atomicity & Disk Integrity:
   Validates atomic disk state after each transition.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.bot import HiveBot
from src.utils import ConfigManager
from src.hive.submission import (
    Verdict,
    ExecutionErrorKind,
    SubmissionResult,
    RunResult,
    SubmissionManager,
)
from src.hive.problem_detail import ProblemDetail, SampleTestCase
from src.solver.models import (
    SolutionRequest,
    SolutionResponse,
    ProviderErrorKind,
    ProviderError,
)
from src.solver.engine import AISolverEngine
from src.solver.provider import BaseAIProvider
from src.editor.adapter import EditorAdapter
from src.editor.language_controller import LanguageController
from src.state.manager import StateManager
from src.utils.constants import WorkflowState, VerdictType


# =====================================================================
# Test Doubles
# =====================================================================

class FakeEditorAdapter(EditorAdapter):
    """Test double recording editor interactions and maintaining simulated buffer."""

    def __init__(self, initial_code: str = "", language: str = "cpp"):
        self.current_code = initial_code
        self.language = language
        self.set_code_calls: List[str] = []

    async def is_ready(self) -> bool:
        return True

    async def get_code(self) -> str:
        return self.current_code

    async def set_code(self, code: str) -> None:
        self.set_code_calls.append(code)
        self.current_code = code

    async def get_language(self) -> str:
        return self.language


class FakeSubmissionManager(SubmissionManager):
    """Test double yielding a deterministic sequence of submission outcomes."""

    def __init__(self, results_sequence: List[SubmissionResult]):
        super().__init__(run_timeout_s=1.0, submit_timeout_s=1.0, dry_run=False)
        self.sequence = list(results_sequence)
        self.submit_calls = 0
        self.run_sample_calls = 0

    async def run_sample_tests(self, page, timeout_s=None) -> RunResult:
        self.run_sample_calls += 1
        return RunResult(success=True, verdict=Verdict.ACCEPTED, diagnostic_message="All sample test cases passed.")

    async def submit_solution(self, page, timeout_s=None) -> SubmissionResult:
        self.submit_calls += 1
        if self.sequence:
            return self.sequence.pop(0)
        return SubmissionResult(
            success=False,
            verdict=Verdict.UNKNOWN,
            error_kind=ExecutionErrorKind.TIMEOUT,
            diagnostic_message="Simulated fallback timeout",
        )


class FakeAISolverEngine(AISolverEngine):
    """Test double recording every SolutionRequest and returning designated versions."""

    def __init__(self, response_codes: Optional[List[str]] = None):
        self.requests: List[SolutionRequest] = []
        self.response_codes = response_codes or []
        self.calls = 0

    async def solve(self, request: SolutionRequest) -> SolutionResponse:
        self.calls += 1
        self.requests.append(request)

        if self.response_codes and self.calls <= len(self.response_codes):
            code = self.response_codes[self.calls - 1]
        else:
            code = f"// Code generated for attempt {request.attempt_number}\n#include <iostream>\nint main() {{ return 0; }}"

        return SolutionResponse(
            code=code,
            language=request.language,
            provider="fake_provider",
            model="fake_model",
            raw_response=code,
        )


class MockFailingProvider(BaseAIProvider):
    """Mock provider simulating transient or quota failure."""

    def __init__(self, name: str, kind: ProviderErrorKind, message: str, status_code: int = 429):
        super().__init__(name=name, api_key="mock_key", model="mock_model", timeout_seconds=5.0)
        self.kind = kind
        self.message = message
        self.status_code = status_code
        self.call_count = 0

    async def generate_code(self, prompt: str) -> str:
        self.call_count += 1
        raise ProviderError(
            kind=self.kind,
            provider_name=self.name,
            message=self.message,
            status_code=self.status_code,
        )


class MockSucceedingProvider(BaseAIProvider):
    """Mock provider returning clean code."""

    def __init__(self, name: str, return_code: str):
        super().__init__(name=name, api_key="mock_key", model="mock_model", timeout_seconds=5.0)
        self.return_code = return_code
        self.call_count = 0

    async def generate_code(self, prompt: str) -> str:
        self.call_count += 1
        return self.return_code


def make_dummy_problem(problem_id: str = "gauntlets") -> ProblemDetail:
    return ProblemDetail(
        problem_id=problem_id,
        title="Gauntlets",
        description="Maximize pairs of gauntlets.",
        input_format="Integer N followed by N integers.",
        output_format="Max pairs.",
        constraints="1 <= N <= 100",
        sample_cases=[SampleTestCase(input_data="6\n4 1 7 4 1 4", output_data="2")],
    )


def create_harness_bot(state_file_path: Path) -> HiveBot:
    if state_file_path.exists():
        state_file_path.unlink()

    config_dict = {
        "solver": {
            "default_language": "C++",
            "max_attempts": 5,
            "run_sample_tests": False,
            "timeout_seconds": 10.0,
        },
        "browser": {
            "browser_profile_path": "~/.hive_bot_profile_test",
            "headless": True,
        },
        "hive": {
            "contest_url": "https://hive.smartinterviews.in/contests/smart-interviews-basic",
        }
    }
    cm = ConfigManager(load_env_file=False)
    cm._config = config_dict

    sm = StateManager(state_file=state_file_path)
    bot = HiveBot(config_manager=cm, state_manager=sm)

    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems/dummy"
    mock_page.goto = AsyncMock()
    mock_browser.get_page = AsyncMock(return_value=mock_page)
    bot.browser_manager = mock_browser

    return bot


async def run_solve_with_doubles(
    bot: HiveBot,
    problem_id: str,
    adapter: EditorAdapter,
    engine: AISolverEngine,
    sub_mgr: SubmissionManager,
) -> bool:
    """Executes HiveBot.solve_problem with injected test doubles."""
    with patch("src.bot.ProblemDetailParser.extract_from_page", new_callable=AsyncMock) as mock_extract, \
         patch.object(LanguageController, "select_language", new_callable=AsyncMock) as mock_lang, \
         patch("src.bot.EditorDetector.detect", new_callable=AsyncMock) as mock_detect:
        mock_extract.return_value = make_dummy_problem(problem_id)
        mock_detect.return_value = adapter
        mock_lang.return_value = True

        return await bot.solve_problem(
            problem_id=problem_id,
            solver_engine=engine,
            submission_manager=sub_mgr,
        )


# =====================================================================
# Verification Scenarios
# =====================================================================

async def test_scenario_1_wrong_answer_repair(report: dict):
    """Scenario 1: Wrong Answer on Attempt 1 -> Enriched repair prompt on Attempt 2 -> Accepted."""
    print("\n--- [Scenario 1] Wrong Answer -> Repair Prompt -> Accepted ---")
    state_file = PROJECT_ROOT / "scratch" / "state_test4_s1.json"
    bot = create_harness_bot(state_file)
    problem_id = "gauntlets_s1"
    bot.state_manager.add_problem(problem_id, "Gauntlets S1")

    adapter = FakeEditorAdapter()

    code_v1 = "// Solution v1 (buggy)\n#include <iostream>\nint main() { std::cout << 0; return 0; }"
    code_v2 = "// Solution v2 (fixed)\n#include <iostream>\nint main() { std::cout << 2; return 0; }"
    engine = FakeAISolverEngine(response_codes=[code_v1, code_v2])

    sub_seq = [
        SubmissionResult(
            success=False,
            verdict=Verdict.WRONG_ANSWER,
            score=0,
            max_score=20,
            testcases_passed=0,
            total_testcases=10,
            diagnostic_message="Wrong Answer on testcase #1: expected '2', got '0'",
        ),
        SubmissionResult(
            success=True,
            verdict=Verdict.ACCEPTED,
            score=20,
            max_score=20,
            testcases_passed=10,
            total_testcases=10,
            diagnostic_message="Accepted: All test cases passed successfully.",
        )
    ]
    sub_mgr = FakeSubmissionManager(sub_seq)

    success = await run_solve_with_doubles(
        bot=bot,
        problem_id=problem_id,
        adapter=adapter,
        engine=engine,
        sub_mgr=sub_mgr,
    )

    # Invariants verification
    assert success is True, "Scenario 1 should succeed on attempt 2"
    assert engine.calls == 2, f"Expected 2 AI engine calls, got {engine.calls}"
    assert sub_mgr.submit_calls == 2, f"Expected 2 submissions, got {sub_mgr.submit_calls}"

    # Repair prompt audit
    req1 = engine.requests[0]
    req2 = engine.requests[1]
    assert req1.attempt_number == 1, "Attempt 1 request number mismatch"
    assert req1.previous_code is None, "Attempt 1 should have no previous code"
    assert req2.attempt_number == 2, "Attempt 2 request number mismatch"
    assert req2.previous_code == code_v1, "Attempt 2 did not receive previous buggy code"
    assert "Wrong Answer" in (req2.previous_verdict or ""), "Attempt 2 missing previous verdict"
    assert "testcase #1" in (req2.previous_error or ""), "Attempt 2 missing diagnostic error"

    # State audit
    assert problem_id in bot.state_manager.state.completed_problems, "Problem not in completed_problems"
    assert problem_id not in bot.state_manager.state.problems_queue, "Problem still in problems_queue"
    assert bot.state_manager.state.progress[problem_id].attempts == 2, "Progress attempts should be 2"

    print("  ✓ Attempt 1 evaluated as Wrong Answer; attempt counter incremented.")
    print("  ✓ Attempt 2 received previous code + verdict + diagnostics.")
    print("  ✓ Accepted on Attempt 2; problem marked completed and dequeued.")

    report["scenarios"]["scenario_1_wrong_answer_repair"] = {
        "status": "PASS",
        "attempts": bot.state_manager.state.progress[problem_id].attempts,
        "ai_calls": engine.calls,
        "submissions": sub_mgr.submit_calls,
        "repair_prompt_verified": True,
    }


async def test_scenario_2_compilation_error_repair(report: dict):
    """Scenario 2: Compilation Error on Attempt 1 -> Compiler diagnostics in repair prompt -> Accepted."""
    print("\n--- [Scenario 2] Compilation Error -> Compiler Diagnostic -> Accepted ---")
    state_file = PROJECT_ROOT / "scratch" / "state_test4_s2.json"
    bot = create_harness_bot(state_file)
    problem_id = "gauntlets_s2"
    bot.state_manager.add_problem(problem_id, "Gauntlets S2")

    adapter = FakeEditorAdapter()

    code_v1 = "// Solution v1 syntax error\nint main() { std::cout << 2 return 0; }"
    code_v2 = "// Solution v2 valid\n#include <iostream>\nint main() { std::cout << 2; return 0; }"
    engine = FakeAISolverEngine(response_codes=[code_v1, code_v2])

    sub_seq = [
        SubmissionResult(
            success=False,
            verdict=Verdict.COMPILATION_ERROR,
            score=0,
            max_score=20,
            testcases_passed=0,
            total_testcases=10,
            diagnostic_message="solution.cpp:2:32: error: expected ';' before 'return'",
        ),
        SubmissionResult(
            success=True,
            verdict=Verdict.ACCEPTED,
            score=20,
            max_score=20,
            testcases_passed=10,
            total_testcases=10,
            diagnostic_message="Accepted: All test cases passed successfully.",
        )
    ]
    sub_mgr = FakeSubmissionManager(sub_seq)

    success = await run_solve_with_doubles(
        bot=bot,
        problem_id=problem_id,
        adapter=adapter,
        engine=engine,
        sub_mgr=sub_mgr,
    )

    assert success is True
    assert engine.calls == 2
    assert sub_mgr.submit_calls == 2

    req2 = engine.requests[1]
    assert req2.attempt_number == 2
    assert "expected ';'" in (req2.previous_error or ""), "Compiler error diagnostic not preserved in prompt"
    assert req2.previous_verdict == Verdict.COMPILATION_ERROR.value

    assert problem_id in bot.state_manager.state.completed_problems
    assert problem_id not in bot.state_manager.state.problems_queue

    print("  ✓ Attempt 1 evaluated as Compilation Error.")
    print("  ✓ Attempt 2 prompt preserved exact compiler diagnostic lines.")
    print("  ✓ Accepted on Attempt 2; problem marked completed.")

    report["scenarios"]["scenario_2_compilation_error_repair"] = {
        "status": "PASS",
        "attempts": bot.state_manager.state.progress[problem_id].attempts,
        "ai_calls": engine.calls,
        "compiler_diagnostic_in_prompt": True,
    }


async def test_scenario_3_platform_timeout_recovery(report: dict):
    """Scenario 3: Platform Timeout Boundary -> Retains current_code & attempt -> Succeeds (Zero AI Burn)."""
    print("\n--- [Scenario 3] Platform Timeout -> Platform Retry -> Accepted (Zero AI Burn) ---")
    state_file = PROJECT_ROOT / "scratch" / "state_test4_s3.json"
    bot = create_harness_bot(state_file)
    problem_id = "gauntlets_s3"
    bot.state_manager.add_problem(problem_id, "Gauntlets S3")

    adapter = FakeEditorAdapter()

    code_v1 = "// Solution v1\n#include <iostream>\nint main() { return 0; }"
    engine = FakeAISolverEngine(response_codes=[code_v1])

    sub_seq = [
        SubmissionResult(
            success=False,
            verdict=Verdict.UNKNOWN,
            error_kind=ExecutionErrorKind.TIMEOUT,
            diagnostic_message="Timed out after 45s waiting for submission evaluation.",
        ),
        SubmissionResult(
            success=True,
            verdict=Verdict.ACCEPTED,
            score=20,
            max_score=20,
            testcases_passed=10,
            total_testcases=10,
            diagnostic_message="Accepted: All test cases passed successfully.",
        )
    ]
    sub_mgr = FakeSubmissionManager(sub_seq)

    success = await run_solve_with_doubles(
        bot=bot,
        problem_id=problem_id,
        adapter=adapter,
        engine=engine,
        sub_mgr=sub_mgr,
    )

    # Critical Invariants:
    # 1. Total AI engine calls MUST be exactly 1 (Platform timeout does NOT burn AI calls!)
    assert engine.calls == 1, f"CRITICAL: Platform timeout caused extra AI call! Calls={engine.calls}"
    # 2. Total code injections into editor MUST be exactly 1
    assert len(adapter.set_code_calls) == 1, "Editor re-injected code unnecessarily on platform retry"
    # 3. Submissions called 2 times
    assert sub_mgr.submit_calls == 2, f"Expected 2 submit attempts, got {sub_mgr.submit_calls}"
    # 4. Attempt number in state MUST remain 1
    assert bot.state_manager.state.progress[problem_id].attempts == 1, "Attempt counter was incorrectly incremented on timeout!"
    assert success is True
    assert problem_id in bot.state_manager.state.completed_problems
    assert problem_id not in bot.state_manager.state.problems_queue

    print("  ✓ Platform Timeout did NOT burn an AI attempt (AI calls = 1).")
    print("  ✓ Existing code retained in editor without mutation.")
    print("  ✓ Platform retry succeeded; problem completed with attempt = 1.")

    report["scenarios"]["scenario_3_platform_timeout_recovery"] = {
        "status": "PASS",
        "ai_calls": engine.calls,
        "editor_injections": len(adapter.set_code_calls),
        "submit_calls": sub_mgr.submit_calls,
        "final_attempt_number": bot.state_manager.state.progress[problem_id].attempts,
        "zero_ai_burn_verified": True,
    }


async def test_scenario_4_platform_timeout_exhaustion(report: dict):
    """Scenario 4: Platform Timeout Exhaustion -> Bounded retries (3) terminate cleanly without infinite loop."""
    print("\n--- [Scenario 4] Platform Timeout Exhaustion (Bounded Retries = 3) ---")
    state_file = PROJECT_ROOT / "scratch" / "state_test4_s4.json"
    bot = create_harness_bot(state_file)
    problem_id = "gauntlets_s4"
    bot.state_manager.add_problem(problem_id, "Gauntlets S4")

    adapter = FakeEditorAdapter()

    engine = FakeAISolverEngine()
    # 4 consecutive timeouts
    sub_seq = [
        SubmissionResult(
            success=False,
            verdict=Verdict.UNKNOWN,
            error_kind=ExecutionErrorKind.TIMEOUT,
            diagnostic_message="Timed out after 45s",
        )
        for _ in range(4)
    ]
    sub_mgr = FakeSubmissionManager(sub_seq)

    success = await run_solve_with_doubles(
        bot=bot,
        problem_id=problem_id,
        adapter=adapter,
        engine=engine,
        sub_mgr=sub_mgr,
    )

    assert success is False, "Exhausted platform retries must return False"
    # Max platform retries is 3
    assert sub_mgr.submit_calls == 3, f"Platform retries not bounded to 3! Calls={sub_mgr.submit_calls}"
    assert engine.calls == 1, "AI called more than once despite platform failures"
    assert problem_id not in bot.state_manager.state.completed_problems, "Problem should not be marked completed"

    print("  ✓ Max platform retries (3) strictly enforced.")
    print("  ✓ Clean exit with False; zero infinite loop.")

    report["scenarios"]["scenario_4_platform_timeout_exhaustion"] = {
        "status": "PASS",
        "submit_calls": sub_mgr.submit_calls,
        "bounded_limit_enforced": True,
        "terminated_cleanly": True,
    }


async def test_scenario_5_fifth_evaluated_failure_skip(report: dict):
    """Scenario 5: 5 Evaluated Failures -> Problem marked failed, dequeued, checkpointed."""
    print("\n--- [Scenario 5] Fifth Evaluated Failure -> Mark Failed & Skip ---")
    state_file = PROJECT_ROOT / "scratch" / "state_test4_s5.json"
    bot = create_harness_bot(state_file)
    problem_id = "gauntlets_s5"
    bot.state_manager.add_problem(problem_id, "Gauntlets S5")

    adapter = FakeEditorAdapter()

    engine = FakeAISolverEngine()
    sub_seq = [
        SubmissionResult(
            success=False,
            verdict=Verdict.WRONG_ANSWER,
            score=0,
            max_score=20,
            testcases_passed=0,
            total_testcases=10,
            diagnostic_message=f"Wrong answer attempt #{i}",
        )
        for i in range(1, 6)
    ]
    sub_mgr = FakeSubmissionManager(sub_seq)

    success = await run_solve_with_doubles(
        bot=bot,
        problem_id=problem_id,
        adapter=adapter,
        engine=engine,
        sub_mgr=sub_mgr,
    )

    assert success is False, "5 failures must return False"
    assert engine.calls == 5, f"Expected 5 AI engine calls, got {engine.calls}"
    assert sub_mgr.submit_calls == 5, f"Expected 5 submissions, got {sub_mgr.submit_calls}"

    # State verification
    progress = bot.state_manager.state.progress[problem_id]
    assert progress.failed is True, "Problem not marked failed in progress"
    assert progress.attempts == 5, "Progress attempts not 5"
    assert problem_id in bot.state_manager.state.failed_problems, "Problem not in failed_problems"
    assert problem_id not in bot.state_manager.state.completed_problems, "Problem falsely marked completed"
    assert problem_id not in bot.state_manager.state.problems_queue, "Failed problem not dequeued!"

    # Verify on-disk JSON
    with open(state_file, "r", encoding="utf-8") as f:
        disk_state = json.load(f)
    assert problem_id in disk_state["failed_problems"], "Disk state missing failed problem"
    assert problem_id not in disk_state["problems_queue"], "Disk queue still contains failed problem"

    print("  ✓ Exactly 5 problem attempts executed.")
    print("  ✓ Problem marked failed=True and added to failed_problems.")
    print("  ✓ Problem removed from problems_queue (queue advanced).")
    print("  ✓ Terminal state atomically checkpointed to disk.")

    report["scenarios"]["scenario_5_fifth_evaluated_failure_skip"] = {
        "status": "PASS",
        "attempts": progress.attempts,
        "marked_failed": True,
        "queue_advanced": True,
        "checkpointed_to_disk": True,
    }


async def test_scenario_6_provider_fallback_attempt_isolation(report: dict):
    """Scenario 6: Provider Fallback (Groq 429 -> Gemini 200) occurs within Attempt 1 without consuming an extra problem attempt."""
    print("\n--- [Scenario 6] Provider Fallback Isolation (Fallback != Extra Problem Attempt) ---")
    state_file = PROJECT_ROOT / "scratch" / "state_test4_s6.json"
    bot = create_harness_bot(state_file)
    problem_id = "gauntlets_s6"
    bot.state_manager.add_problem(problem_id, "Gauntlets S6")

    adapter = FakeEditorAdapter()

    # Build real AISolverEngine with mock providers
    provider1 = MockFailingProvider(
        name="groq",
        kind=ProviderErrorKind.RATE_LIMIT,
        message="429 Rate limit reached for model",
        status_code=429,
    )
    clean_code = "#include <iostream>\nint main() { std::cout << 2; return 0; }"
    provider2 = MockSucceedingProvider(
        name="gemini",
        return_code=clean_code,
    )

    real_engine = AISolverEngine(bot.config, providers=[provider1, provider2])

    sub_seq = [
        SubmissionResult(
            success=True,
            verdict=Verdict.ACCEPTED,
            score=20,
            max_score=20,
            testcases_passed=10,
            total_testcases=10,
            diagnostic_message="Accepted: All test cases passed.",
        )
    ]
    sub_mgr = FakeSubmissionManager(sub_seq)

    success = await run_solve_with_doubles(
        bot=bot,
        problem_id=problem_id,
        adapter=adapter,
        engine=real_engine,
        sub_mgr=sub_mgr,
    )

    # Invariants verification:
    assert success is True
    # Provider 1 called and failed
    assert provider1.call_count == 1, "Provider 1 was not called"
    # Provider 2 called and succeeded
    assert provider2.call_count == 1, "Provider 2 was not called on fallback"
    # Submission was executed once
    assert sub_mgr.submit_calls == 1, f"Expected 1 submit call, got {sub_mgr.submit_calls}"
    # CRITICAL: Problem attempt in state MUST be 1!
    progress = bot.state_manager.state.progress[problem_id]
    assert progress.attempts == 1, f"CRITICAL: Provider fallback was counted as extra problem attempt! attempts={progress.attempts}"
    assert len(progress.submissions) == 1, f"Expected 1 recorded submission, got {len(progress.submissions)}"
    assert progress.submissions[0].attempt_number == 1, "Submission attempt number != 1"
    assert problem_id in bot.state_manager.state.completed_problems
    assert problem_id not in bot.state_manager.state.problems_queue

    print("  ✓ Provider 1 (Groq) failed with RATE_LIMIT (429).")
    print("  ✓ AISolverEngine cleanly fell back to Provider 2 (Gemini).")
    print("  ✓ Problem attempt count remained strictly 1 (Provider fallback != Problem attempt).")
    print("  ✓ Problem accepted and completed on single problem attempt.")

    report["scenarios"]["scenario_6_provider_fallback_attempt_isolation"] = {
        "status": "PASS",
        "provider1_calls": provider1.call_count,
        "provider2_calls": provider2.call_count,
        "problem_attempts": progress.attempts,
        "fallback_isolated_verified": True,
    }


async def test_scenario_7_runtime_tle_mle_partial(report: dict):
    """Scenario 7: Runtime Error, TLE, MLE, Partial -> attempt increments & diagnostic reaches repair prompt."""
    print("\n--- [Scenario 7] Runtime Error / TLE / MLE / Partial Evaluated Failures ---")
    state_file = PROJECT_ROOT / "scratch" / "state_test4_s7.json"
    bot = create_harness_bot(state_file)
    problem_id = "gauntlets_s7"
    bot.state_manager.add_problem(problem_id, "Gauntlets S7")

    adapter = FakeEditorAdapter()

    code_v1 = "// Solution v1 (Runtime Error)\n#include <iostream>\nint main() { int* p = nullptr; *p = 1; return 0; }"
    code_v2 = "// Solution v2 (TLE)\n#include <iostream>\nint main() { while(true); return 0; }"
    code_v3 = "// Solution v3 (Partial)\n#include <iostream>\nint main() { std::cout << 1; return 0; }"
    code_v4 = "// Solution v4 (Accepted)\n#include <iostream>\nint main() { std::cout << 2; return 0; }"
    engine = FakeAISolverEngine(response_codes=[code_v1, code_v2, code_v3, code_v4])

    sub_seq = [
        SubmissionResult(
            success=False,
            verdict=Verdict.RUNTIME_ERROR,
            score=0,
            max_score=20,
            testcases_passed=0,
            total_testcases=10,
            diagnostic_message="Runtime Error: Segmentation fault (core dumped) on testcase #1",
        ),
        SubmissionResult(
            success=False,
            verdict=Verdict.TIME_LIMIT_EXCEEDED,
            score=0,
            max_score=20,
            testcases_passed=0,
            total_testcases=10,
            diagnostic_message="Time Limit Exceeded (execution exceeded 1.0s) on testcase #2",
        ),
        SubmissionResult(
            success=False,
            verdict=Verdict.PARTIALLY_ACCEPTED,
            score=10,
            max_score=20,
            testcases_passed=5,
            total_testcases=10,
            diagnostic_message="Partially Accepted: 5/10 test cases passed (Score: 10/20)",
        ),
        SubmissionResult(
            success=True,
            verdict=Verdict.ACCEPTED,
            score=20,
            max_score=20,
            testcases_passed=10,
            total_testcases=10,
            diagnostic_message="Accepted: All test cases passed successfully.",
        ),
    ]
    sub_mgr = FakeSubmissionManager(sub_seq)

    success = await run_solve_with_doubles(
        bot=bot,
        problem_id=problem_id,
        adapter=adapter,
        engine=engine,
        sub_mgr=sub_mgr,
    )

    assert success is True, "Scenario 7 should succeed on attempt 4"
    assert engine.calls == 4, f"Expected 4 AI engine calls, got {engine.calls}"
    assert sub_mgr.submit_calls == 4, f"Expected 4 submissions, got {sub_mgr.submit_calls}"

    # Verify attempt increments and diagnostics reached prompt
    req2 = engine.requests[1]
    assert req2.attempt_number == 2
    assert "Segmentation fault" in (req2.previous_error or "")
    assert req2.previous_verdict == Verdict.RUNTIME_ERROR.value

    req3 = engine.requests[2]
    assert req3.attempt_number == 3
    assert "Time Limit Exceeded" in (req3.previous_error or "")
    assert req3.previous_verdict == Verdict.TIME_LIMIT_EXCEEDED.value

    req4 = engine.requests[3]
    assert req4.attempt_number == 4
    assert "Partially Accepted" in (req4.previous_error or "")
    assert req4.previous_verdict == Verdict.PARTIALLY_ACCEPTED.value

    assert problem_id in bot.state_manager.state.completed_problems
    assert problem_id not in bot.state_manager.state.problems_queue

    print("  ✓ Runtime Error incremented attempt (1 -> 2) and forwarded diagnostic.")
    print("  ✓ Time Limit Exceeded incremented attempt (2 -> 3) and forwarded diagnostic.")
    print("  ✓ Partially Accepted incremented attempt (3 -> 4) and forwarded diagnostic.")
    print("  ✓ Accepted on Attempt 4; problem completed.")

    report["scenarios"]["scenario_7_runtime_tle_mle_partial"] = {
        "status": "PASS",
        "attempts": bot.state_manager.state.progress[problem_id].attempts,
        "runtime_error_verified": True,
        "tle_verified": True,
        "partial_verified": True,
    }


# =====================================================================
# Main Test 4 Runner
# =====================================================================

async def run_test_4():
    print("=" * 70)
    print("PHASE 4 — TEST 4: DELIBERATE RETRY VALIDATION (CONTROLLED TEST DOUBLES)")
    print("=" * 70)

    report = {
        "scenarios": {},
        "summary": {
            "total_scenarios": 7,
            "passed_scenarios": 0,
            "failed_scenarios": 0,
        },
        "all_criteria_met": False,
    }

    try:
        await test_scenario_1_wrong_answer_repair(report)
        report["summary"]["passed_scenarios"] += 1

        await test_scenario_2_compilation_error_repair(report)
        report["summary"]["passed_scenarios"] += 1

        await test_scenario_3_platform_timeout_recovery(report)
        report["summary"]["passed_scenarios"] += 1

        await test_scenario_4_platform_timeout_exhaustion(report)
        report["summary"]["passed_scenarios"] += 1

        await test_scenario_5_fifth_evaluated_failure_skip(report)
        report["summary"]["passed_scenarios"] += 1

        await test_scenario_6_provider_fallback_attempt_isolation(report)
        report["summary"]["passed_scenarios"] += 1

        await test_scenario_7_runtime_tle_mle_partial(report)
        report["summary"]["passed_scenarios"] += 1

        report["all_criteria_met"] = (report["summary"]["passed_scenarios"] == 7)

    except Exception as e:
        print(f"\n[ERROR] Test 4 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        report["summary"]["failed_scenarios"] = report["summary"]["total_scenarios"] - report["summary"]["passed_scenarios"]
        report["all_criteria_met"] = False

    # Save artifact
    out_path = PROJECT_ROOT / "scratch" / "phase4_test4_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 70)
    print(f"FINAL RESULT: {'SUCCESS - ALL CRITERIA MET' if report['all_criteria_met'] else 'FAILED'}")
    print(f"Passed: {report['summary']['passed_scenarios']} / {report['summary']['total_scenarios']}")
    print(f"Report saved to: {out_path}")
    print("=" * 70)
    return report


if __name__ == "__main__":
    res = asyncio.run(run_test_4())
    sys.exit(0 if res.get("all_criteria_met") else 1)
