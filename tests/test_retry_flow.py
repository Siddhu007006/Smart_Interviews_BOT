"""
Unit tests for Step 7: Bot Solve Loop Integration & Retry State Machine.

Verifies:
1. Immediate acceptance on Attempt 1: marks completed, saves checkpoint, advances queue.
2. Evaluated code failure on Attempt 1: burns attempt, feeds diagnostics into Attempt 2 prompt, succeeds on Attempt 2.
3. Platform/bot failure (TIMEOUT): does NOT burn an AI attempt, retries platform interaction.
4. Max attempts exhaustion (5 attempts failed): marks failed/skipped, saves checkpoint, advances queue.
5. Crash resilience & checkpoint atomicity: already-accepted problem is skipped without re-solving.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.bot import HiveBot
from src.utils.config import ConfigManager
from src.hive.submission import (
    Verdict,
    ExecutionErrorKind,
    SubmissionResult,
    SubmissionManager,
)
from src.hive.problem_detail import ProblemDetail, SampleTestCase
from src.solver.models import SolutionRequest, SolutionResponse
from src.solver.engine import AISolverEngine
from src.editor.adapter import EditorAdapter
from src.utils.constants import WorkflowState, VerdictType


def make_dummy_problem_detail(problem_id="max-element-in-array"):
    return ProblemDetail(
        problem_id=problem_id,
        title="Max Element in Array",
        description="Find max element in array.",
        input_format="N integers.",
        output_format="Max integer.",
        constraints="1 <= N <= 1000",
        sample_cases=[SampleTestCase(input_data="3\n1 2 3", output_data="3")],
    )


@pytest.fixture
def mock_bot(temp_dir, monkeypatch):
    """Fixture providing an initialized HiveBot with mock dependencies and isolated state."""
    # Create isolated state manager with temp dir
    from src.state.manager import StateManager
    
    test_state_file = temp_dir / "state.json"
    test_state_manager = StateManager(state_file=test_state_file)
    
    config_file = temp_dir / "config.yaml"
    config_file.write_text("""
browser:
  browser_profile_path: ~/.hive_bot_test
  headless: true
auth:
  login_url: https://hive.smartinterviews.in/login
hive:
  contest_url: https://hive.smartinterviews.in/contests/smart-interviews-basic
solver:
  default_language: C++
  max_attempts: 5
  run_sample_tests: false
""", encoding="utf-8")

    cm = ConfigManager(config_file=str(config_file), load_env_file=False)
    
    # Pass isolated state manager to bot
    bot = HiveBot(config_manager=cm, state_manager=test_state_manager)

    # Verify state file is correctly isolated
    assert bot.state_manager.state_file == test_state_file

    # Mock browser and page
    mock_browser = MagicMock()
    mock_page = MagicMock()
    mock_page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems/max-element-in-array"
    mock_page.goto = AsyncMock()
    mock_browser.get_page = AsyncMock(return_value=mock_page)
    bot.browser_manager = mock_browser

    return bot, mock_page


@pytest.mark.asyncio
async def test_solve_problem_accepted_first_attempt(mock_bot):
    """Verify problem is marked completed on first attempt, advancing queue and checkpointing state."""
    bot, mock_page = mock_bot
    problem_id = "max-element-in-array"
    bot.state_manager.state.problems_queue.append(problem_id)

    # Mock ProblemDetailParser, LanguageController, and EditorDetector
    with patch("src.hive.ProblemDetailParser.extract_from_page", new_callable=AsyncMock) as mock_extract, \
         patch("src.editor.LanguageController.select_language", new_callable=AsyncMock) as mock_lang, \
         patch("src.editor.EditorDetector.detect", new_callable=AsyncMock) as mock_detect:

        mock_extract.return_value = make_dummy_problem_detail(problem_id)
        mock_adapter = MagicMock(spec=EditorAdapter)
        mock_adapter.is_ready = AsyncMock(return_value=True)
        mock_adapter.set_code = AsyncMock(return_value=True)
        mock_detect.return_value = mock_adapter

        # Mock SolverEngine: returns valid C++ code
        mock_engine = MagicMock(spec=AISolverEngine)
        mock_engine.solve = AsyncMock(return_value=SolutionResponse(
            code="#include <iostream>\nint main() { return 0; }",
            language="C++",
            provider="groq",
            model="test-model",
            raw_response="code"
        ))

        # Mock SubmissionManager: returns Accepted on Attempt 1
        mock_sub_mgr = MagicMock(spec=SubmissionManager)
        mock_sub_mgr.submit_solution = AsyncMock(return_value=SubmissionResult(
            success=True,
            verdict=Verdict.ACCEPTED,
            score=20,
            max_score=20,
            testcases_passed=10,
            total_testcases=10,
            diagnostic_message="All test cases passed."
        ))

        success = await bot.solve_problem(
            problem_id=problem_id,
            solver_engine=mock_engine,
            submission_manager=mock_sub_mgr
        )

        assert success is True
        # Invariants verified:
        assert problem_id in bot.state_manager.state.completed_problems
        assert problem_id not in bot.state_manager.state.problems_queue
        assert bot.state_manager.state.progress[problem_id].solved is True
        assert bot.state_manager.state.progress[problem_id].attempts == 1
        assert len(bot.state_manager.state.progress[problem_id].submissions) == 1
        mock_engine.solve.assert_called_once()
        mock_sub_mgr.submit_solution.assert_called_once()


@pytest.mark.asyncio
async def test_solve_problem_code_failure_burns_attempt_and_heals_on_attempt_2(mock_bot):
    """Verify code failure burns an AI attempt, provides diagnostics to next prompt, and heals."""
    bot, mock_page = mock_bot
    problem_id = "max-element-in-array"
    bot.state_manager.state.problems_queue.append(problem_id)

    with patch("src.hive.ProblemDetailParser.extract_from_page", new_callable=AsyncMock) as mock_extract, \
         patch("src.editor.LanguageController.select_language", new_callable=AsyncMock) as mock_lang, \
         patch("src.editor.EditorDetector.detect", new_callable=AsyncMock) as mock_detect:

        mock_extract.return_value = make_dummy_problem_detail(problem_id)
        mock_adapter = MagicMock(spec=EditorAdapter)
        mock_adapter.is_ready = AsyncMock(return_value=True)
        mock_adapter.set_code = AsyncMock(return_value=True)
        mock_detect.return_value = mock_adapter

        # Mock SolverEngine: returns attempt-specific code
        call_count = 0
        requests_received = []

        async def mock_solve(req: SolutionRequest):
            nonlocal call_count
            call_count += 1
            requests_received.append(req)
            return SolutionResponse(
                code=f"// Attempt {call_count}\n#include <iostream>\nint main() {{ return 0; }}",
                language="C++",
                provider="groq",
                model="test-model",
                raw_response=""
            )

        mock_engine = MagicMock(spec=AISolverEngine)
        mock_engine.solve = AsyncMock(side_effect=mock_solve)

        # Mock SubmissionManager: Attempt 1 = Wrong Answer, Attempt 2 = Accepted
        sub_call_count = 0
        async def mock_submit(page):
            nonlocal sub_call_count
            sub_call_count += 1
            if sub_call_count == 1:
                return SubmissionResult(
                    success=False,
                    verdict=Verdict.WRONG_ANSWER,
                    score=0,
                    max_score=20,
                    diagnostic_message="Wrong Answer on testcase #1: Expected 15, got 0"
                )
            return SubmissionResult(
                success=True,
                verdict=Verdict.ACCEPTED,
                score=20,
                max_score=20,
                diagnostic_message="All test cases passed."
            )

        mock_sub_mgr = MagicMock(spec=SubmissionManager)
        mock_sub_mgr.submit_solution = AsyncMock(side_effect=mock_submit)

        success = await bot.solve_problem(
            problem_id=problem_id,
            solver_engine=mock_engine,
            submission_manager=mock_sub_mgr
        )

        assert success is True
        assert call_count == 2
        assert sub_call_count == 2

        # Check that Attempt 2 prompt received cumulative error context
        attempt2_req = requests_received[1]
        assert attempt2_req.attempt_number == 2
        assert attempt2_req.previous_code == "// Attempt 1\n#include <iostream>\nint main() { return 0; }"
        assert attempt2_req.previous_error == "Wrong Answer on testcase #1: Expected 15, got 0"
        assert attempt2_req.previous_verdict == "Wrong Answer"

        # Final state
        assert problem_id in bot.state_manager.state.completed_problems
        assert bot.state_manager.state.progress[problem_id].attempts == 2


@pytest.mark.asyncio
async def test_solve_problem_platform_failure_does_not_burn_ai_attempt(mock_bot):
    """Verify platform TIMEOUT does NOT burn an AI attempt; retries submission and succeeds."""
    bot, mock_page = mock_bot
    problem_id = "max-element-in-array"
    bot.state_manager.state.problems_queue.append(problem_id)

    with patch("src.hive.ProblemDetailParser.extract_from_page", new_callable=AsyncMock) as mock_extract, \
         patch("src.editor.LanguageController.select_language", new_callable=AsyncMock) as mock_lang, \
         patch("src.editor.EditorDetector.detect", new_callable=AsyncMock) as mock_detect:

        mock_extract.return_value = make_dummy_problem_detail(problem_id)
        mock_adapter = MagicMock(spec=EditorAdapter)
        mock_adapter.is_ready = AsyncMock(return_value=True)
        mock_adapter.set_code = AsyncMock(return_value=True)
        mock_detect.return_value = mock_adapter

        ai_calls = 0
        async def mock_solve(req: SolutionRequest):
            nonlocal ai_calls
            ai_calls += 1
            return SolutionResponse(
                code="#include <iostream>\nint main() { return 0; }",
                language="C++",
                provider="groq",
                model="test-model",
                raw_response=""
            )

        mock_engine = MagicMock(spec=AISolverEngine)
        mock_engine.solve = AsyncMock(side_effect=mock_solve)

        # Submission 1: TIMEOUT (platform failure), Submission 2: Accepted
        sub_calls = 0
        async def mock_submit(page):
            nonlocal sub_calls
            sub_calls += 1
            if sub_calls == 1:
                return SubmissionResult(
                    success=False,
                    verdict=Verdict.UNKNOWN,
                    error_kind=ExecutionErrorKind.TIMEOUT,
                    diagnostic_message="Timed out waiting for submission evaluation."
                )
            return SubmissionResult(
                success=True,
                verdict=Verdict.ACCEPTED,
                score=20,
                max_score=20,
                diagnostic_message="All test cases passed."
            )

        mock_sub_mgr = MagicMock(spec=SubmissionManager)
        mock_sub_mgr.submit_solution = AsyncMock(side_effect=mock_submit)

        success = await bot.solve_problem(
            problem_id=problem_id,
            solver_engine=mock_engine,
            submission_manager=mock_sub_mgr
        )

        assert success is True
        # CRITICAL RULE: AI attempt was NOT burned for platform failure!
        # AI solver was called ONLY ONCE because the generated code was unchanged.
        assert ai_calls == 1
        assert sub_calls == 2
        assert bot.state_manager.state.progress[problem_id].attempts == 1
        assert problem_id in bot.state_manager.state.completed_problems


@pytest.mark.asyncio
async def test_solve_problem_max_attempts_exhausted_marks_failed(mock_bot):
    """Verify exhausting all 5 attempts marks problem as failed and skips."""
    bot, mock_page = mock_bot
    problem_id = "max-element-in-array"
    bot.state_manager.state.problems_queue.append(problem_id)

    with patch("src.hive.ProblemDetailParser.extract_from_page", new_callable=AsyncMock) as mock_extract, \
         patch("src.editor.LanguageController.select_language", new_callable=AsyncMock) as mock_lang, \
         patch("src.editor.EditorDetector.detect", new_callable=AsyncMock) as mock_detect:

        mock_extract.return_value = make_dummy_problem_detail(problem_id)
        mock_adapter = MagicMock(spec=EditorAdapter)
        mock_adapter.is_ready = AsyncMock(return_value=True)
        mock_adapter.set_code = AsyncMock(return_value=True)
        mock_detect.return_value = mock_adapter

        mock_engine = MagicMock(spec=AISolverEngine)
        mock_engine.solve = AsyncMock(return_value=SolutionResponse(
            code="#include <iostream>\nint main() { return 0; }",
            language="C++",
            provider="groq",
            model="test-model",
            raw_response=""
        ))

        # Always returns Wrong Answer
        mock_sub_mgr = MagicMock(spec=SubmissionManager)
        mock_sub_mgr.submit_solution = AsyncMock(return_value=SubmissionResult(
            success=False,
            verdict=Verdict.WRONG_ANSWER,
            score=0,
            max_score=20,
            diagnostic_message="Wrong Answer on hidden test case."
        ))

        success = await bot.solve_problem(
            problem_id=problem_id,
            solver_engine=mock_engine,
            submission_manager=mock_sub_mgr
        )

        assert success is False
        # Invariants: exactly 5 attempts burned
        assert mock_engine.solve.call_count == 5
        assert mock_sub_mgr.submit_solution.call_count == 5
        assert problem_id in bot.state_manager.state.failed_problems
        assert problem_id not in bot.state_manager.state.completed_problems
        assert problem_id not in bot.state_manager.state.problems_queue
        assert bot.state_manager.state.progress[problem_id].failed is True


@pytest.mark.asyncio
async def test_solve_problem_already_completed_skipped_crash_resilience(mock_bot):
    """Verify crash resilience: already-completed problem is skipped immediately without re-solving."""
    bot, mock_page = mock_bot
    problem_id = "max-element-in-array"
    # Pre-mark completed in state
    bot.state_manager.mark_problem_solved(problem_id)

    mock_engine = MagicMock(spec=AISolverEngine)
    mock_sub_mgr = MagicMock(spec=SubmissionManager)

    success = await bot.solve_problem(
        problem_id=problem_id,
        solver_engine=mock_engine,
        submission_manager=mock_sub_mgr
    )

    assert success is True
    # Zero browser/solver calls made
    mock_page.goto.assert_not_called()
    mock_engine.solve.assert_not_called()
    mock_sub_mgr.submit_solution.assert_not_called()


@pytest.mark.asyncio
async def test_solve_problems_loop_advances_queue(mock_bot):
    """Verify solve_problems iterates through queue and updates statistics."""
    bot, mock_page = mock_bot
    p1 = "problem-1"
    p2 = "problem-2"
    bot.state_manager.state.problems_queue = [p1, p2]

    async def mock_solve_problem(problem_id=None, *args, **kwargs):
        pid = problem_id or kwargs.get("problem_id")
        if pid == p1:
            bot.state_manager.mark_problem_solved(pid)
            return True
        else:
            bot.state_manager.mark_problem_failed(pid, "Failed")
            return False

    with patch.object(bot, "solve_problem", side_effect=mock_solve_problem):
        stats = await bot.solve_problems()

    assert stats["completed"] == 1
    assert stats["failed"] == 1
    assert bot.state_manager.state.session.workflow_state == WorkflowState.COMPLETE
