"""
Unit tests for Hive Submission and Verdict Handling (Step 6).

Covers:
Run:
- sample accepted
- sample failed
- actual vs expected extraction
- Run timeout
- missing result / button

Submit:
- Accepted
- Wrong Answer
- Compilation Error
- Runtime Error
- TLE
- unknown verdict
- submission timeout
- diagnostic extraction

Preserves distinction:
Hive says code failed != Bot failed to determine what Hive said
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.hive.submission import (
    Verdict,
    ExecutionErrorKind,
    SampleCaseResult,
    RunResult,
    SubmissionResult,
    SubmissionParser,
    SubmissionManager,
)


# =====================================================================
# Pure Parser Tests: Run Sample Test Cases
# =====================================================================

def test_parse_run_accepted():
    """Verify clean parsing of Accepted sample test case."""
    raw_console = """Result
Custom Input

Accepted (Sample Test Case)

Input
5
-2 -19 8 15 4

Output
15
"""
    result = SubmissionParser.parse_run_output(raw_console)

    assert result.success is True
    assert result.verdict == Verdict.ACCEPTED
    assert result.error_kind is None
    assert result.is_verdict_determined is True
    assert result.is_platform_failure is False
    assert len(result.sample_cases) == 1
    assert result.sample_cases[0].passed is True
    assert result.sample_cases[0].input_data == "5\n-2 -19 8 15 4"
    assert result.sample_cases[0].actual_output == "15"


def test_parse_run_failed_with_diff():
    """Verify parsing of Wrong sample test case with actual and expected outputs."""
    raw_console = """Result
Custom Input

Wrong (Sample Test Case)

Input
5
-2 -19 8 15 4

Output
12

Expected Output
15
"""
    result = SubmissionParser.parse_run_output(raw_console)

    assert result.success is False
    assert result.verdict == Verdict.WRONG_ANSWER
    assert result.error_kind is None
    assert result.is_verdict_determined is True
    assert result.is_platform_failure is False
    assert len(result.sample_cases) == 1
    assert result.sample_cases[0].passed is False
    assert result.sample_cases[0].input_data == "5\n-2 -19 8 15 4"
    assert result.sample_cases[0].actual_output == "12"
    assert result.sample_cases[0].expected_output == "15"
    assert "Actual Output:\n12" in result.diagnostic_message
    assert "Expected Output:\n15" in result.diagnostic_message


def test_parse_run_compilation_error():
    """Verify parsing of Compilation Error in Run mode."""
    raw_console = """Result
Custom Input

Compilation Error
main.cpp: In function 'int main()':
main.cpp:10:5: error: expected ';' before 'return'
    return 0;
    ^~~~~~
"""
    result = SubmissionParser.parse_run_output(raw_console)

    assert result.success is False
    assert result.verdict == Verdict.COMPILATION_ERROR
    assert result.error_kind is None
    assert result.is_verdict_determined is True
    assert "error: expected ';'" in result.diagnostic_message


def test_parse_run_runtime_error():
    """Verify parsing of Runtime Error (e.g. SIGSEGV) in Run mode."""
    raw_console = """Result
Custom Input

Runtime Error
Execution killed with signal 11 (SIGSEGV)
"""
    result = SubmissionParser.parse_run_output(raw_console)

    assert result.success is False
    assert result.verdict == Verdict.RUNTIME_ERROR
    assert result.error_kind is None
    assert result.is_verdict_determined is True
    assert "SIGSEGV" in result.diagnostic_message


def test_parse_run_time_limit_exceeded():
    """Verify parsing of Time Limit Exceeded in Run mode."""
    raw_console = """Result
Custom Input

Time Limit Exceeded
Execution timed out after 2.00 seconds
"""
    result = SubmissionParser.parse_run_output(raw_console)

    assert result.success is False
    assert result.verdict == Verdict.TIME_LIMIT_EXCEEDED
    assert result.error_kind is None
    assert result.is_verdict_determined is True


def test_parse_run_missing_result_empty_text():
    """Verify empty console text results in MISSING_RESULT error kind, NOT Wrong Answer."""
    result = SubmissionParser.parse_run_output("   ")

    assert result.success is False
    assert result.verdict == Verdict.UNKNOWN
    assert result.error_kind == ExecutionErrorKind.MISSING_RESULT
    assert result.is_verdict_determined is False
    assert result.is_platform_failure is True


def test_parse_run_unrecognized_verdict():
    """Verify unrecognized text results in UNRECOGNIZED_VERDICT error kind."""
    result = SubmissionParser.parse_run_output("Internal proxy gateway buffer overflow error 0x9923")

    assert result.success is False
    assert result.verdict == Verdict.UNKNOWN
    assert result.error_kind == ExecutionErrorKind.UNRECOGNIZED_VERDICT
    assert result.is_verdict_determined is False
    assert result.is_platform_failure is True


# =====================================================================
# Pure Parser Tests: Submit Final Solution
# =====================================================================

def test_parse_submit_accepted():
    """Verify parsing of Accepted submission with score and test case counts."""
    console_text = """Result
Custom Input

Accepted

Score: 20 / 20

✓ Case #1    ✓ Case #2    ✓ Case #3
✓ Case #4    ✓ Case #5    ✓ Case #6
✓ Case #7    ✓ Case #8    ✓ Case #9
✓ Case #10
"""
    toast_text = """Max Element In Array
All hidden testcases passed.
"""
    result = SubmissionParser.parse_submission_output(console_text, toast_text)

    assert result.success is True
    assert result.verdict == Verdict.ACCEPTED
    assert result.score == 20
    assert result.max_score == 20
    assert result.testcases_passed == 10
    assert result.total_testcases == 10
    assert result.error_kind is None
    assert result.is_verdict_determined is True
    assert result.is_platform_failure is False


def test_parse_submit_wrong_answer():
    """Verify parsing of Wrong Answer submission with partial score."""
    console_text = """Result
Custom Input

Wrong Answer

Score: 6 / 20

✓ Case #1    ✓ Case #2    ✓ Case #3
✗ Case #4    ✗ Case #5    ✗ Case #6
✗ Case #7    ✗ Case #8    ✗ Case #9
✗ Case #10
"""
    toast_text = """Max Element In Array
7 testcases failed.
"""
    result = SubmissionParser.parse_submission_output(console_text, toast_text)

    assert result.success is False
    assert result.verdict == Verdict.WRONG_ANSWER
    assert result.score == 6
    assert result.max_score == 20
    assert result.testcases_passed == 3
    assert result.total_testcases == 10
    assert result.error_kind is None
    assert result.is_verdict_determined is True
    assert result.is_platform_failure is False
    assert "Score: 6/20" in result.diagnostic_message


def test_parse_submit_compilation_error():
    """Verify parsing of Compilation Error submission."""
    console_text = """Result
Custom Input

Compilation Error
solution.java:5: error: cannot find symbol
    System.out.printlln("test");
              ^
"""
    result = SubmissionParser.parse_submission_output(console_text)

    assert result.success is False
    assert result.verdict == Verdict.COMPILATION_ERROR
    assert result.score == 0
    assert result.error_kind is None
    assert result.is_verdict_determined is True
    assert "cannot find symbol" in result.diagnostic_message


def test_parse_submit_runtime_error():
    """Verify parsing of Runtime Error submission."""
    console_text = """Result
Custom Input

Runtime Error
java.lang.ArrayIndexOutOfBoundsException: Index 10 out of bounds for length 5
"""
    result = SubmissionParser.parse_submission_output(console_text)

    assert result.success is False
    assert result.verdict == Verdict.RUNTIME_ERROR
    assert result.score == 0
    assert result.error_kind is None
    assert result.is_verdict_determined is True
    assert "ArrayIndexOutOfBoundsException" in result.diagnostic_message


def test_parse_submit_time_limit_exceeded():
    """Verify parsing of Time Limit Exceeded submission."""
    console_text = """Result
Custom Input

Time Limit Exceeded

Score: 0 / 20
"""
    result = SubmissionParser.parse_submission_output(console_text)

    assert result.success is False
    assert result.verdict == Verdict.TIME_LIMIT_EXCEEDED
    assert result.score == 0
    assert result.max_score == 20
    assert result.error_kind is None
    assert result.is_verdict_determined is True


def test_parse_submit_partially_accepted():
    """Verify parsing of Partially Accepted score."""
    console_text = """Result
Custom Input

Partially Solved

Score: 10 / 20

✓ Case #1    ✓ Case #2    ✓ Case #3    ✓ Case #4    ✓ Case #5
"""
    result = SubmissionParser.parse_submission_output(console_text)

    assert result.success is False
    assert result.verdict == Verdict.PARTIALLY_ACCEPTED
    assert result.score == 10
    assert result.max_score == 20
    assert result.error_kind is None
    assert result.is_verdict_determined is True


def test_parse_submit_unknown_verdict():
    """Verify unparseable submission output is classified as UNRECOGNIZED_VERDICT."""
    console_text = "502 Bad Gateway: nginx/1.18.0"
    result = SubmissionParser.parse_submission_output(console_text)

    assert result.success is False
    assert result.verdict == Verdict.UNKNOWN
    assert result.error_kind == ExecutionErrorKind.UNRECOGNIZED_VERDICT
    assert result.is_verdict_determined is False
    assert result.is_platform_failure is True


# =====================================================================
# Interactive Manager Tests (Playwright Mocking)
# =====================================================================

@pytest.mark.asyncio
async def test_run_sample_tests_interactive_success():
    """Verify interactive sample run execution and polling flow."""
    page = MagicMock()
    mock_btn = AsyncMock()
    page.query_selector = AsyncMock(return_value=mock_btn)

    # Simulate console text changing from empty to Accepted
    eval_call_count = 0
    async def mock_evaluate(script, *args):
        nonlocal eval_call_count
        eval_call_count += 1
        if eval_call_count == 1:
            return ""  # Initial check before click
        return "Accepted (Sample Test Case)\nInput\n1\nOutput\n1"

    page.evaluate = AsyncMock(side_effect=mock_evaluate)

    manager = SubmissionManager(run_timeout_s=5.0)
    result = await manager.run_sample_tests(page)

    mock_btn.click.assert_called_once()
    assert result.success is True
    assert result.verdict == Verdict.ACCEPTED
    assert result.error_kind is None


@pytest.mark.asyncio
async def test_run_sample_tests_polling_timeout():
    """Verify polling timeout produces TIMEOUT error_kind, NEVER Wrong Answer."""
    page = MagicMock()
    mock_btn = AsyncMock()
    page.query_selector = AsyncMock(return_value=mock_btn)
    page.evaluate = AsyncMock(return_value="Evaluating...")

    manager = SubmissionManager(run_timeout_s=0.2)
    result = await manager.run_sample_tests(page)

    assert result.success is False
    assert result.verdict == Verdict.UNKNOWN
    assert result.error_kind == ExecutionErrorKind.TIMEOUT
    assert result.is_platform_failure is True
    assert result.is_verdict_determined is False
    # CRITICAL: Polling timeout must NEVER become Wrong Answer
    assert result.verdict != Verdict.WRONG_ANSWER


@pytest.mark.asyncio
async def test_run_sample_tests_missing_button():
    """Verify missing Run button produces MISSING_RESULT error_kind."""
    page = MagicMock()
    page.query_selector = AsyncMock(return_value=None)

    manager = SubmissionManager(run_timeout_s=1.0)
    result = await manager.run_sample_tests(page)

    assert result.success is False
    assert result.verdict == Verdict.UNKNOWN
    assert result.error_kind == ExecutionErrorKind.MISSING_RESULT
    assert result.is_platform_failure is True


@pytest.mark.asyncio
async def test_submit_solution_interactive_success():
    """Verify interactive submit execution and polling flow."""
    page = MagicMock()
    mock_btn = AsyncMock()
    page.query_selector = AsyncMock(return_value=mock_btn)

    async def mock_evaluate(script, *args):
        if "toasts" in script:
            return "Max Element In Array\nAll hidden testcases passed."
        return "Accepted\nScore: 20 / 20"

    page.evaluate = AsyncMock(side_effect=mock_evaluate)

    manager = SubmissionManager(submit_timeout_s=5.0)
    result = await manager.submit_solution(page)

    mock_btn.click.assert_called_once()
    assert result.success is True
    assert result.verdict == Verdict.ACCEPTED
    assert result.score == 20
    assert result.error_kind is None


@pytest.mark.asyncio
async def test_submit_solution_polling_timeout():
    """Verify polling timeout on submit produces TIMEOUT error_kind, NEVER Wrong Answer."""
    page = MagicMock()
    mock_btn = AsyncMock()
    page.query_selector = AsyncMock(return_value=mock_btn)
    page.evaluate = AsyncMock(return_value="Pending...")

    manager = SubmissionManager(submit_timeout_s=0.2)
    result = await manager.submit_solution(page)

    assert result.success is False
    assert result.verdict == Verdict.UNKNOWN
    assert result.error_kind == ExecutionErrorKind.TIMEOUT
    assert result.is_platform_failure is True
    assert result.is_verdict_determined is False
    # CRITICAL: Polling timeout must NEVER become Wrong Answer
    assert result.verdict != Verdict.WRONG_ANSWER


@pytest.mark.asyncio
async def test_submit_solution_missing_button():
    """Verify missing Submit button produces MISSING_RESULT error_kind."""
    page = MagicMock()
    page.query_selector = AsyncMock(return_value=None)

    manager = SubmissionManager(submit_timeout_s=1.0)
    result = await manager.submit_solution(page)

    assert result.success is False
    assert result.verdict == Verdict.UNKNOWN
    assert result.error_kind == ExecutionErrorKind.MISSING_RESULT
    assert result.is_platform_failure is True


@pytest.mark.asyncio
async def test_submit_solution_dry_run_guard_raises():
    """Verify that dry_run=True raises SubmissionError and refuses to submit."""
    from src.utils.errors import SubmissionError
    page = MagicMock()
    page.query_selector = AsyncMock()

    manager = SubmissionManager(dry_run=True)
    with pytest.raises(SubmissionError, match="Submission prohibited: dry-run mode is active"):
        await manager.submit_solution(page)

    page.query_selector.assert_not_called()
