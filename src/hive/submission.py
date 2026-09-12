"""
Submission & Verdict Handling for Hive.

Orchestrates:
1. Running sample test cases via 'Run' button.
2. Submitting final solutions via 'Submit' button.
3. Parsing verdicts (Accepted, Wrong Answer, Compilation Error, Runtime Error, Time Limit Exceeded).
4. Strictly distinguishing between code failure (Hive says code failed) and
   platform/bot evaluation failure (Bot failed to determine what Hive said).
"""

from dataclasses import dataclass, field
from enum import Enum
import re
import asyncio
from typing import List, Optional, Dict, Any, Tuple

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.hive.ui_constants import (
    RUN_CODE_BUTTON,
    SUBMIT_CODE_BUTTON,
    CONSOLE_DRAWER,
    CONSOLE_TOGGLE_BUTTON,
)
from src.utils.errors import VerdictError, SubmissionError, TimeoutError as BotTimeoutError
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class Verdict(str, Enum):
    """Normalized verdict categories returned by the platform."""
    ACCEPTED = "Accepted"
    WRONG_ANSWER = "Wrong Answer"
    COMPILATION_ERROR = "Compilation Error"
    RUNTIME_ERROR = "Runtime Error"
    TIME_LIMIT_EXCEEDED = "Time Limit Exceeded"
    MEMORY_LIMIT_EXCEEDED = "Memory Limit Exceeded"
    PARTIALLY_ACCEPTED = "Partially Accepted"
    UNKNOWN = "Unknown"


class ExecutionErrorKind(str, Enum):
    """
    Platform / Bot evaluation failure kinds.
    Enforces the distinction: Hive says code failed != Bot failed to determine what Hive said.
    """
    TIMEOUT = "TIMEOUT"                         # Polling timed out before evaluation completed
    DISCONNECTED = "DISCONNECTED"               # Browser closed or connection severed
    UNRECOGNIZED_VERDICT = "UNRECOGNIZED"       # Content rendered but could not be matched to a known verdict
    MISSING_RESULT = "MISSING_RESULT"           # Result container / button not found in DOM
    EXECUTION_FAILED = "EXECUTION_FAILED"       # Generic script evaluation error


@dataclass
class SampleCaseResult:
    """Outcome details for an individual sample test case in Run mode."""
    passed: bool
    input_data: str = ""
    actual_output: str = ""
    expected_output: str = ""
    raw_text: str = ""


@dataclass
class RunResult:
    """Result of running code against sample test cases."""
    success: bool
    verdict: Verdict
    raw_output: str = ""
    sample_cases: List[SampleCaseResult] = field(default_factory=list)
    diagnostic_message: str = ""
    error_kind: Optional[ExecutionErrorKind] = None

    @property
    def is_verdict_determined(self) -> bool:
        """True if the platform returned an evaluable verdict (even if code failed)."""
        return self.error_kind is None and self.verdict != Verdict.UNKNOWN

    @property
    def is_platform_failure(self) -> bool:
        """True if the bot or platform failed to determine the result."""
        return self.error_kind is not None


@dataclass
class SubmissionResult:
    """Result of submitting code against all hidden test cases."""
    success: bool
    verdict: Verdict
    score: Optional[int] = None
    max_score: Optional[int] = None
    testcases_passed: Optional[int] = None
    total_testcases: Optional[int] = None
    raw_output: str = ""
    diagnostic_message: str = ""
    error_kind: Optional[ExecutionErrorKind] = None

    @property
    def is_verdict_determined(self) -> bool:
        """True if the platform returned an evaluable verdict (even if code failed)."""
        return self.error_kind is None and self.verdict != Verdict.UNKNOWN

    @property
    def is_platform_failure(self) -> bool:
        """True if the bot or platform failed to determine the result."""
        return self.error_kind is not None


class SubmissionParser:
    """
    Deterministic pure parser for Hive test case and submission outputs.
    Separated from Playwright page interactions for direct testability.
    """

    @classmethod
    def parse_run_output(cls, console_text: str, html: Optional[str] = None) -> RunResult:
        """
        Parse console drawer output from a sample 'Run' execution.
        """
        if not console_text or not console_text.strip():
            return RunResult(
                success=False,
                verdict=Verdict.UNKNOWN,
                error_kind=ExecutionErrorKind.MISSING_RESULT,
                diagnostic_message="Console text is empty",
                raw_output=""
            )

        text = console_text.strip()
        text_lower = text.lower()

        # 1. Check for compilation error
        if "compilation error" in text_lower or "compile error" in text_lower:
            diag = cls._extract_compiler_diagnostic(text)
            return RunResult(
                success=False,
                verdict=Verdict.COMPILATION_ERROR,
                raw_output=text,
                diagnostic_message=diag
            )

        # 2. Check for runtime error
        if "runtime error" in text_lower or "sigsegv" in text_lower or "execution killed" in text_lower:
            diag = cls._extract_runtime_diagnostic(text)
            return RunResult(
                success=False,
                verdict=Verdict.RUNTIME_ERROR,
                raw_output=text,
                diagnostic_message=diag
            )

        # 3. Check for time limit exceeded
        if "time limit exceeded" in text_lower or "timed out" in text_lower or "execution timeout" in text_lower:
            return RunResult(
                success=False,
                verdict=Verdict.TIME_LIMIT_EXCEEDED,
                raw_output=text,
                diagnostic_message="Sample execution timed out (Time Limit Exceeded)"
            )

        # 4. Check for Accepted (Sample Test Case)
        is_accepted = (
            "accepted (sample test case)" in text_lower
            or "passed (sample test case)" in text_lower
            or ("accepted" in text_lower and "wrong" not in text_lower and "failed" not in text_lower)
        )

        # 5. Check for Wrong (Sample Test Case)
        is_wrong = (
            "wrong (sample test case)" in text_lower
            or "failed (sample test case)" in text_lower
            or "wrong answer" in text_lower
            or "wrong" in text_lower
        )

        sample_cases = cls._extract_sample_case_details(text)

        if is_accepted and not is_wrong:
            return RunResult(
                success=True,
                verdict=Verdict.ACCEPTED,
                raw_output=text,
                sample_cases=sample_cases,
                diagnostic_message="All sample test cases passed."
            )

        if is_wrong:
            diag_parts = ["Sample test case failed."]
            for idx, sc in enumerate(sample_cases, 1):
                if not sc.passed:
                    if sc.input_data:
                        diag_parts.append(f"Input:\n{sc.input_data}")
                    if sc.actual_output:
                        diag_parts.append(f"Actual Output:\n{sc.actual_output}")
                    if sc.expected_output:
                        diag_parts.append(f"Expected Output:\n{sc.expected_output}")

            return RunResult(
                success=False,
                verdict=Verdict.WRONG_ANSWER,
                raw_output=text,
                sample_cases=sample_cases,
                diagnostic_message="\n".join(diag_parts)
            )

        # If text is present but cannot be parsed into any known verdict
        return RunResult(
            success=False,
            verdict=Verdict.UNKNOWN,
            error_kind=ExecutionErrorKind.UNRECOGNIZED_VERDICT,
            raw_output=text,
            diagnostic_message=f"Unrecognized sample run result: {text[:200]}"
        )

    @classmethod
    def parse_submission_output(
        cls,
        console_text: str,
        toast_text: Optional[str] = None,
        html: Optional[str] = None
    ) -> SubmissionResult:
        """
        Parse console drawer and toast notifications from a final 'Submit' execution.
        """
        combined = (console_text or "") + "\n" + (toast_text or "")
        combined_strip = combined.strip()

        if not combined_strip:
            return SubmissionResult(
                success=False,
                verdict=Verdict.UNKNOWN,
                error_kind=ExecutionErrorKind.MISSING_RESULT,
                diagnostic_message="Submission output is empty",
                raw_output=""
            )

        combined_lower = combined_strip.lower()

        # Score extraction
        score = None
        max_score = None
        score_match = re.search(r"score:\s*(\d+)\s*\/\s*(\d+)", combined_strip, re.IGNORECASE)
        if score_match:
            score = int(score_match.group(1))
            max_score = int(score_match.group(2))

        # Test cases passed/total extraction
        testcases_passed, total_testcases = cls._extract_testcase_counts(combined_strip)

        # 1. Compilation Error
        if "compilation error" in combined_lower or "compile error" in combined_lower:
            diag = cls._extract_compiler_diagnostic(console_text)
            return SubmissionResult(
                success=False,
                verdict=Verdict.COMPILATION_ERROR,
                score=score or 0,
                max_score=max_score,
                testcases_passed=0,
                total_testcases=total_testcases,
                raw_output=combined_strip,
                diagnostic_message=diag
            )

        # 2. Time Limit Exceeded
        if "time limit exceeded" in combined_lower or "tle" in combined_lower:
            return SubmissionResult(
                success=False,
                verdict=Verdict.TIME_LIMIT_EXCEEDED,
                score=score or 0,
                max_score=max_score,
                testcases_passed=testcases_passed,
                total_testcases=total_testcases,
                raw_output=combined_strip,
                diagnostic_message="Solution exceeded time limit on hidden test cases."
            )

        # 3. Runtime Error
        if "runtime error" in combined_lower or "sigsegv" in combined_lower:
            diag = cls._extract_runtime_diagnostic(console_text)
            return SubmissionResult(
                success=False,
                verdict=Verdict.RUNTIME_ERROR,
                score=score or 0,
                max_score=max_score,
                testcases_passed=testcases_passed,
                total_testcases=total_testcases,
                raw_output=combined_strip,
                diagnostic_message=diag
            )

        # 4. Memory Limit Exceeded
        if "memory limit exceeded" in combined_lower:
            return SubmissionResult(
                success=False,
                verdict=Verdict.MEMORY_LIMIT_EXCEEDED,
                score=score or 0,
                max_score=max_score,
                testcases_passed=testcases_passed,
                total_testcases=total_testcases,
                raw_output=combined_strip,
                diagnostic_message="Solution exceeded memory limit."
            )

        # 5. Accepted
        is_accepted = (
            ("accepted" in combined_lower and "partially" not in combined_lower and "wrong" not in combined_lower and "sample test case" not in combined_lower)
            or "all hidden testcases passed" in combined_lower
        )
        if score is not None and max_score is not None:
            if score == max_score and score > 0:
                is_accepted = True

        if is_accepted:
            return SubmissionResult(
                success=True,
                verdict=Verdict.ACCEPTED,
                score=score if score is not None else (max_score or 20),
                max_score=max_score or (score or 20),
                testcases_passed=testcases_passed or total_testcases,
                total_testcases=total_testcases or testcases_passed,
                raw_output=combined_strip,
                diagnostic_message="Accepted: All test cases passed successfully."
            )

        # 6. Wrong Answer (takes precedence over score-based partial credit if explicitly marked Wrong)
        if "wrong answer" in combined_lower or "wrong" in combined_lower or "testcase failed" in combined_lower:
            return SubmissionResult(
                success=False,
                verdict=Verdict.WRONG_ANSWER,
                score=score or 0,
                max_score=max_score,
                testcases_passed=testcases_passed or 0,
                total_testcases=total_testcases,
                raw_output=combined_strip,
                diagnostic_message=f"Wrong Answer on hidden test cases (Score: {score or 0}/{max_score or '?'})."
            )

        # 7. Partially Solved / Partially Accepted
        if (score is not None and max_score is not None and 0 < score < max_score) or "partially" in combined_lower:
            return SubmissionResult(
                success=False,
                verdict=Verdict.PARTIALLY_ACCEPTED,
                score=score,
                max_score=max_score,
                testcases_passed=testcases_passed,
                total_testcases=total_testcases,
                raw_output=combined_strip,
                diagnostic_message=f"Partially accepted: Score {score}/{max_score}. {testcases_passed or 'Some'} test cases passed."
            )

        # 8. Unrecognized verdict
        return SubmissionResult(
            success=False,
            verdict=Verdict.UNKNOWN,
            score=score,
            max_score=max_score,
            testcases_passed=testcases_passed,
            total_testcases=total_testcases,
            raw_output=combined_strip,
            error_kind=ExecutionErrorKind.UNRECOGNIZED_VERDICT,
            diagnostic_message=f"Unrecognized submission verdict from Hive: {combined_strip[:200]}"
        )

    @classmethod
    def _extract_sample_case_details(cls, text: str) -> List[SampleCaseResult]:
        """Extract input, actual output, and expected output from sample test case results."""
        results: List[SampleCaseResult] = []

        is_accepted = "accepted" in text.lower() and "wrong" not in text.lower()

        # Isolate the standalone Input section (avoiding 'Custom Input')
        input_match = re.search(
            r"^[ \t]*Input[ \t]*\n+([\s\S]*?)(?=\n+[ \t]*(?:Output|Expected Output)|\s*\Z)",
            text,
            re.IGNORECASE | re.MULTILINE
        )
        output_match = re.search(
            r"^[ \t]*Output[ \t]*\n+([\s\S]*?)(?=\n+[ \t]*Expected Output|\s*\Z)",
            text,
            re.IGNORECASE | re.MULTILINE
        )
        expected_match = re.search(
            r"^[ \t]*Expected Output[ \t]*\n+([\s\S]*?)(?=\s*\Z)",
            text,
            re.IGNORECASE | re.MULTILINE
        )

        input_data = input_match.group(1).strip() if input_match else ""
        actual_output = output_match.group(1).strip() if output_match else ""
        expected_output = expected_match.group(1).strip() if expected_match else ""

        if input_data or actual_output or expected_output:
            results.append(SampleCaseResult(
                passed=is_accepted,
                input_data=input_data,
                actual_output=actual_output,
                expected_output=expected_output,
                raw_text=text
            ))

        return results

    @classmethod
    def _extract_testcase_counts(cls, text: str) -> Tuple[Optional[int], Optional[int]]:
        """Extract passed and total test cases count from testcase icons or summary."""
        cases = re.findall(r"Case\s*#(\d+)", text, re.IGNORECASE)
        if cases:
            case_nums = [int(c) for c in cases]
            total = max(case_nums)
            passed_count = len(re.findall(r"(?:✓|pass|accepted)\s*Case\s*#\d+", text, re.IGNORECASE))
            if passed_count > 0:
                return passed_count, total
            if "accepted" in text.lower() and "wrong" not in text.lower():
                return total, total
            return None, total

        m = re.search(r"(\d+)\s*\/\s*(\d+)\s*(?:passed|testcases)", text, re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))

        return None, None

    @classmethod
    def _extract_compiler_diagnostic(cls, text: str) -> str:
        """Extract compiler error lines and strip UI navigation boilerplate."""
        lines = text.splitlines()
        diag_lines = []
        capture = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if "compilation error" in stripped.lower() or "error:" in stripped.lower():
                capture = True
            if capture:
                if stripped in ("Result", "Custom Input", "Console"):
                    continue
                diag_lines.append(line)

        if diag_lines:
            return "\n".join(diag_lines).strip()
        return text.strip()

    @classmethod
    def _extract_runtime_diagnostic(cls, text: str) -> str:
        """Extract runtime error details."""
        lines = text.splitlines()
        diag_lines = [
            l for l in lines
            if l.strip() and l.strip() not in ("Result", "Custom Input", "Console")
        ]
        return "\n".join(diag_lines).strip()


class SubmissionManager:
    """
    Manages interactive execution of Run and Submit on Hive's live problem page.
    """

    def __init__(
        self,
        run_timeout_s: float = 30.0,
        submit_timeout_s: float = 45.0,
        dry_run: bool = False,
    ):
        self.run_timeout_s = run_timeout_s
        self.submit_timeout_s = submit_timeout_s
        self.dry_run = dry_run

    async def run_sample_tests(self, page: Page, timeout_s: Optional[float] = None) -> RunResult:
        """
        Click 'Run' button and wait for sample evaluation in console drawer.
        """
        timeout = timeout_s or self.run_timeout_s

        run_btn = await page.query_selector(RUN_CODE_BUTTON)
        if not run_btn:
            logger.error("Run button not found on page")
            return RunResult(
                success=False,
                verdict=Verdict.UNKNOWN,
                error_kind=ExecutionErrorKind.MISSING_RESULT,
                diagnostic_message="Run button not found on problem page"
            )

        initial_text = await self._get_console_text(page)

        logger.info("Clicking 'Run' button for sample test execution...")
        await run_btn.click()

        start_time = asyncio.get_event_loop().time()
        poll_interval = 0.5

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(poll_interval)

            current_text = await self._get_console_text(page)
            if not current_text:
                continue

            lower = current_text.lower()
            has_verdict = any(v in lower for v in (
                "accepted (sample test case)",
                "passed (sample test case)",
                "wrong (sample test case)",
                "failed (sample test case)",
                "compilation error",
                "runtime error",
                "time limit exceeded",
                "sigsegv",
            ))

            if has_verdict and current_text != initial_text:
                logger.info("Sample test execution completed.")
                return SubmissionParser.parse_run_output(current_text)

        logger.warning(f"Timed out after {timeout}s waiting for sample run result.")
        return RunResult(
            success=False,
            verdict=Verdict.UNKNOWN,
            error_kind=ExecutionErrorKind.TIMEOUT,
            diagnostic_message=f"Timed out after {timeout}s waiting for sample run evaluation.",
            raw_output=await self._get_console_text(page)
        )

    async def submit_solution(self, page: Page, timeout_s: Optional[float] = None) -> SubmissionResult:
        """
        Click 'Submit' button and wait for full evaluation result across hidden test cases.
        """
        if self.dry_run:
            logger.warning("Dry-run guard active: submission prohibited.")
            raise SubmissionError("Submission prohibited: dry-run mode is active.")

        timeout = timeout_s or self.submit_timeout_s

        submit_btn = await page.query_selector(SUBMIT_CODE_BUTTON)
        if not submit_btn:
            logger.error("Submit button not found on page")
            return SubmissionResult(
                success=False,
                verdict=Verdict.UNKNOWN,
                error_kind=ExecutionErrorKind.MISSING_RESULT,
                diagnostic_message="Submit button not found on problem page"
            )

        initial_console = await self._get_console_text(page)

        logger.info("Clicking 'Submit' button for full solution evaluation...")
        await submit_btn.click()

        start_time = asyncio.get_event_loop().time()
        poll_interval = 0.5

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            await asyncio.sleep(poll_interval)

            console_text = await self._get_console_text(page)
            toast_text = await self._get_toast_text(page)

            console_lower = (console_text or "").lower()
            toast_lower = (toast_text or "").lower()
            combined_lower = f"{console_lower} {toast_lower}".strip()

            # Toast signals directly confirm hidden testcase verdict
            toast_has_verdict = any(v in toast_lower for v in (
                "all hidden testcases passed",
                "testcases failed",
                "testcase failed",
                "compilation error",
                "runtime error",
                "time limit exceeded",
            ))

            # Console signals: only count if console changed from pre-submit text OR has submission-specific content (score/hidden)
            console_updated = (console_text != initial_console)
            console_has_submission_verdict = (
                "score:" in console_lower
                or ("accepted" in console_lower and "sample test case" not in console_lower)
                or "wrong answer" in console_lower
                or "compilation error" in console_lower
                or "runtime error" in console_lower
                or "time limit exceeded" in console_lower
                or "memory limit exceeded" in console_lower
            )

            if toast_has_verdict or (console_updated and console_has_submission_verdict):
                logger.info("Submission evaluation completed.")
                return SubmissionParser.parse_submission_output(console_text, toast_text)

        logger.warning(f"Timed out after {timeout}s waiting for submission verdict.")
        return SubmissionResult(
            success=False,
            verdict=Verdict.UNKNOWN,
            error_kind=ExecutionErrorKind.TIMEOUT,
            diagnostic_message=f"Timed out after {timeout}s waiting for submission evaluation.",
            raw_output=await self._get_console_text(page)
        )

    async def _get_console_text(self, page: Page) -> str:
        """Safely extract current innerText from the console drawer."""
        try:
            return await page.evaluate('''(selector) => {
                const el = document.querySelector(selector);
                return el ? el.innerText : "";
            }''', CONSOLE_DRAWER)
        except Exception as e:
            logger.debug(f"Failed to read console drawer text: {e}")
            return ""

    async def _get_toast_text(self, page: Page) -> str:
        """Safely extract text from any active snackbar / toast notifications."""
        try:
            return await page.evaluate('''() => {
                const toasts = document.querySelectorAll("mat-snack-bar-container, .mdc-snackbar, .toast, [class*='toast'], [class*='snackbar']");
                if (!toasts || toasts.length === 0) return "";
                return Array.from(toasts).map(t => t.innerText).join("\\n");
            }''')
        except Exception as e:
            logger.debug(f"Failed to read toast text: {e}")
            return ""
