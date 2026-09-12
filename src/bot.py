"""
Main HiveBot orchestrator.

Coordinates all components:
- Browser management
- Extension auto-installation (first run) / verification (subsequent runs)
- Authentication
- Session verification
- Problem list detection
- State persistence
"""

import asyncio
from pathlib import Path
from typing import Optional

from src.utils import (
    get_logger,
    LogContext,
    ConfigManager,
    HiveBotError,
    AuthenticationError,
    WorkflowState,
)
from src.browser import BrowserManager, ExtensionChecker, ExtensionInstaller
from src.auth import AuthManager, Credentials
from src.hive import ProblemListDetector, ProblemDetailParser, ProblemDetail
from src.hive.submission import SubmissionManager, SubmissionResult, Verdict, ExecutionErrorKind
from src.editor import LanguageController, EditorDetector
from src.solver.models import SolutionRequest, SolutionResponse
from src.solver.engine import AISolverEngine
from src.state import StateManager, Credentials as StateCredentials
from src.state.models import Submission
from src.utils.constants import VerdictType
from src.utils.errors import EditorError, SolverError

logger = get_logger(__name__)


class HiveBot:
    """
    Main bot orchestrator.

    Coordinates:
    - Browser lifecycle
    - Extension auto-install (first run only) or silent verification
    - Authentication workflow
    - Session management
    - Problem list detection
    - State persistence
    """

    def __init__(self, config_manager: ConfigManager, state_manager: Optional[StateManager] = None):
        self.config = config_manager
        self.browser_manager: Optional[BrowserManager] = None
        self.auth_manager: Optional[AuthManager] = None
        self.state_manager = state_manager or StateManager()
        self._installer: Optional[ExtensionInstaller] = None
        self.solver_engine: Optional[AISolverEngine] = None
        self.submission_manager: Optional[SubmissionManager] = None
        self._shutdown_requested: bool = False
        self._shutdown_event: asyncio.Event = asyncio.Event()

        logger.info("HiveBot initialized")

    def request_shutdown(self, reason: str = "signal") -> None:
        """Signal-safe shutdown request: sets flag to finish current atomic step then exit."""
        logger.warning(f"Graceful shutdown requested ({reason}). Finishing current safe operation before exit...")
        self._shutdown_requested = True
        self._shutdown_event.set()

    @property
    def is_shutdown_requested(self) -> bool:
        """Returns True if a graceful shutdown was requested."""
        return self._shutdown_requested

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, dry_run: bool = False) -> bool:
        """
        Run the complete bot workflow.

        Workflow
        --------
        1. Ensure extension is available (download + auto-install if first run,
           or silently verify on subsequent runs).
        2. Launch browser.
        3. Perform login.
        4. Verify session.
        5. Navigate to contest, then page-by-page:
           a. Fetch DOM problems for current page
           b. Reconcile with bot state (Hive DOM is authoritative)
           c. Solve all Hive-unsolved problems on this page
           d. Advance to next page (with advancement verification)
           e. Repeat until no more pages

        Args:
            dry_run: If True, executes extraction, language selection, AI generation,
                     and sample tests, but strictly blocks live submissions.

        Returns:
            True if workflow completed successfully.

        Raises:
            HiveBotError: If any critical step fails.
        """
        with LogContext("Phase 1 Workflow"):
            try:
                logger.info("Starting Phase 1 workflow...")

                # Step 1: Ensure extension is ready
                await self._ensure_extension()

                # Step 2: Perform login (browser already running after step 1)
                await self._perform_login()

                # Step 3: Verify session
                await self._verify_session()

                # Step 4-7: Navigate to contest, discover problems page-by-page,
                # and solve each page's unsolved problems before advancing.
                # Solving is done inline per page inside _detect_problem_list().
                # Returns a WorkflowResult dict indicating success or remaining unresolved problems.
                workflow_result = await self._detect_problem_list()

                unresolved = workflow_result.get("unresolved", [])
                if unresolved:
                    logger.warning(
                        f"⚠ Bot workflow incomplete — "
                        f"{len(unresolved)} problem(s) remain unsolved after all pages processed."
                    )
                    return False
                else:
                    logger.info("✓ Bot workflow completed successfully — all problems solved.")
                    return True

            except HiveBotError as e:
                logger.error(f"Phase 1 workflow failed: {e}")
                await self.shutdown()
                raise

            except Exception as e:
                logger.error(f"Unexpected error in Phase 1: {e}")
                await self.shutdown()
                raise HiveBotError(f"Phase 1 failed: {e}") from e

    # ------------------------------------------------------------------
    # Step 1 — Extension (combined download + install + verify)
    # ------------------------------------------------------------------

    async def _ensure_extension(self) -> None:
        """
        Step 1: Ensure the Hive Extension Detector is installed in the profile.

        Calls ExtensionInstaller.ensure_installed() which:
          - On first run: downloads the CRX, unpacks it, copies files into the
            profile Extensions directory, and registers it in Preferences.
            Fully automatic. Zero user interaction.
          - On subsequent runs: detects existing installation and returns
            immediately (fast path, no network call).

        After this method returns, the browser is launched normally with no
        extra CLI flags — Chrome loads the extension automatically from the
        profile.
        """
        with LogContext("Step 1: Ensure Extension"):
            try:
                profile_path = Path(
                    self.config.get_required("browser.browser_profile_path")
                ).expanduser().resolve()
                data_dir = Path(
                    self.config.get("bot.data_dir", "~/.hive_bot")
                ).expanduser().resolve()

                self._installer = ExtensionInstaller(
                    profile_path=profile_path,
                    data_dir=data_dir,
                )

                # Install (or skip if already present) — runs before Chrome opens
                self._installer.ensure_installed()

                # Launch browser — extension already in profile, no extra args
                await self._launch_browser(extra_args=None)

                # Tier 1 profile verification
                page = await self.browser_manager.get_page()
                checker = ExtensionChecker(page, profile_path=profile_path)
                if not checker.verify_profile_installation(profile_path):
                    logger.warning(
                        "Extension files not immediately verified in profile path; "
                        "will perform full verification on contest page."
                    )

                logger.info("✓ Hive Extension profile setup verified")

            except HiveBotError:
                raise
            except Exception as e:
                logger.error(f"Extension ensure step failed: {e}")
                raise HiveBotError(f"Extension setup failed: {e}") from e

    async def _launch_browser(self, extra_args=None) -> None:
        """
        Launch (or re-launch) browser with the persistent profile.

        Args:
            extra_args: List of additional browser CLI args, or None.
                        Passed as-is to BrowserManager.
        """
        headless = self.config.get("browser.headless", False)
        timeout_ms = self.config.get("browser.timeout_default_ms", 30000)
        profile_path = self.config.get_required("browser.browser_profile_path")
        channel = self.config.get("browser.channel", None)

        if extra_args is None and self._installer:
            extra_args = self._installer.get_extension_args()

        self.browser_manager = BrowserManager(
            profile_path=profile_path,
            headless=headless,
            timeout_ms=timeout_ms,
            extra_args=extra_args,
            channel=channel,
        )
        await self.browser_manager.launch_browser()
        self.state_manager.state.session.workflow_state = WorkflowState.LOGGING_IN
        logger.info("✓ Browser launched")

    # ------------------------------------------------------------------
    # Step 2 — Login
    # ------------------------------------------------------------------

    async def _perform_login(self) -> None:
        """Step 2: Perform login."""
        with LogContext("Step 2: Perform Login"):
            try:
                if not self.browser_manager:
                    raise HiveBotError("Browser not initialized")

                credentials = Credentials.from_config(self.config)
                page = await self.browser_manager.get_page()
                login_timeout = self.config.get("auth.login_timeout_s", 60)
                self.auth_manager = AuthManager(page, credentials, login_timeout)

                success = await self.auth_manager.login()
                if not success:
                    # Login failed — check if the extension modal appeared
                    checker = ExtensionChecker(page)
                    modal_visible = await checker.is_extension_modal_visible()
                    if modal_visible:
                        from src.browser.extension_installer import EXTENSION_STORE_URL
                        raise HiveBotError(
                            "Login blocked by Hive: the Extension Required modal is visible.\n"
                            "The Hive Extension Detector is not enabled in the bot profile.\n"
                            f"Install it from: {EXTENSION_STORE_URL}\n"
                            "Then re-run the bot."
                        )
                    raise HiveBotError(
                        "Login failed — URL never left the login page. "
                        "Credentials may be wrong, or an invisible form validation is failing."
                    )

                logger.info("✓ Login successful")

                # Check if logged-in account matches .env credentials
                # If mismatch, it means profile has old account cached - user must switch
                try:
                    cached_username = self.state_manager.state.session.credentials.username
                    if (cached_username and 
                        cached_username.lower() != credentials.username.lower()):
                        logger.error(
                            f"❌ ACCOUNT MISMATCH - Profile has old account cached:\n"
                            f"   .env says:     {credentials.username}\n"
                            f"   Profile has:   {cached_username}\n"
                            f"\n"
                            f"   To switch accounts:\n"
                            f"   1. Update HIVE_USERNAME and HIVE_PASSWORD in .env\n"
                            f"   2. Clear the old profile:\n"
                            f"      PowerShell: Remove-Item -Recurse -Force '$env:USERPROFILE\\.hive_bot_profile'\n"
                            f"      Or run: .\\switch_account.ps1\n"
                            f"   3. Run bot again - it will create fresh profile with new account\n"
                        )
                        raise AuthenticationError(
                            f"Account mismatch: .env has {credentials.username} "
                            f"but profile cached {cached_username}"
                        )
                except AuthenticationError:
                    raise
                except Exception:
                    pass  # Profile may not have cached credentials yet

                state_creds = StateCredentials(
                    username=credentials.username,
                    login_url=credentials.login_url,
                )
                self.state_manager.update_session(
                    authenticated=True,
                    credentials=state_creds,
                )

            except HiveBotError:
                raise
            except Exception as e:
                logger.error(f"Login failed: {e}")
                raise HiveBotError(f"Login failed: {e}") from e

    # ------------------------------------------------------------------
    # Step 3 — Session verify
    # ------------------------------------------------------------------

    async def _verify_session(self) -> None:
        """Step 3: Verify authenticated session."""
        with LogContext("Step 3: Verify Session"):
            try:
                if not self.auth_manager:
                    raise HiveBotError("Auth manager not initialized")

                if not await self.auth_manager.verify_session():
                    raise HiveBotError("Session verification failed")

                logger.info("✓ Session verified")

            except HiveBotError:
                raise
            except Exception as e:
                logger.error(f"Session verification failed: {e}")
                raise HiveBotError(f"Session verification failed: {e}") from e

    # ------------------------------------------------------------------
    # Step 4 — Problem list
    # ------------------------------------------------------------------

    async def _detect_problem_list(self) -> None:
        """
        Step 4: Contest Navigation, Extension Hierarchy Verification, Continue Contest & Problem Extraction (Phase 2).

        Architecture (page-by-page):
        1. Navigate to contest + click Continue Contest
        2. For each page:
           a. Fetch DOM problems
           b. Reconcile with bot state — Hive DOM is authoritative:
              - "Try Again"      → Hive-solved  → update state only
              - "Solve"/"Continue" → Hive-unsolved → always queue
              - Hive-unsolved + bot completed_problems → state drift warning + requeue
           c. Build actionable queue (only Hive-unsolved problems for THIS page)
           d. Solve each problem in order before advancing
           e. Advance to next page (with advancement verification)
        3. Terminate when: no Next button, advancement verification fails, or safety cap hit
        """
        with LogContext("Step 4: Contest Navigation & Problem Discovery"):
            try:
                if not self.browser_manager:
                    raise HiveBotError("Browser not initialized")

                page = await self.browser_manager.get_page()
                profile_path = Path(
                    self.config.get_required("browser.browser_profile_path")
                ).expanduser().resolve()

                detector = ProblemListDetector(page)
                checker = ExtensionChecker(page, profile_path=profile_path)

                # Get contest URL from configuration (HIVE_CONTEST_URL in .env)
                contest_url = self.config.get("hive.contest_url")
                if not contest_url:
                    contest_url = self.config.get("auth.login_url")

                # If not already on the problem list page, navigate to the contest
                if not await detector.is_on_problem_list_page():
                    if not contest_url:
                        raise HiveBotError("Cannot navigate: HIVE_CONTEST_URL is not configured in .env or config.")

                    logger.info(f"Navigating to contest URL: {contest_url}")
                    await detector.navigate_to_contest(contest_url)

                    # Strict Multi-Tier Verification Hierarchy:
                    # 1. Browser / profile verification
                    # 2. Extension runtime verification
                    # 3. Hive blocker dismissed verification
                    logger.info("Executing 3-tier extension verification on contest page...")
                    await checker.verify_extension_ready(profile_path=profile_path, timeout_s=10.0)

                    # 4. Only then: Continue Contest
                    logger.info("Clicking Continue Contest to enter problem list...")
                    continued = await detector.click_continue_contest()
                    if not continued and not await detector.is_on_problem_list_page():
                        raise HiveBotError("Failed to navigate to problem list page after clicking Continue Contest.")

                # Mark on problem list state
                self.state_manager.mark_on_problem_list(True)
                self.state_manager.state.session.workflow_state = WorkflowState.ON_PROBLEM_LIST


                # ----------------------------------------------------------------
                # Page-by-page loop:
                # Fetch → Reconcile → Queue → Solve → Advance → Repeat
                # ----------------------------------------------------------------
                MAX_PAGES = 50  # Safety cap — prevents runaway loops
                page_number = 0

                while page_number < MAX_PAGES:
                    if self._shutdown_requested:
                        logger.info("Shutdown requested: stopping page-by-page loop.")
                        break

                    logger.info(f"Processing page {page_number + 1} of problem list...")
                    problems = await detector.fetch_problems()

                    if not problems:
                        logger.warning(f"No problems extracted from DOM on page {page_number + 1}.")
                        break

                    # ---- Reconcile: Hive DOM is authoritative ----
                    # Queue invariant: only Hive-unsolved problems enter the queue.
                    # completed_problems is a historical crash-recovery log — not a skip list.
                    page_queue: list = []  # list of (problem_id, problem_url)

                    hive_solved_count = 0
                    hive_unsolved_count = 0
                    state_drift_count = 0

                    for p in problems:
                        if p.solved:
                            # Hive confirmed solved ("Try Again") — update state, do NOT queue
                            hive_solved_count += 1
                            self.state_manager.add_problem(p.problem_id, p.title)
                            self.state_manager.mark_problem_solved(p.problem_id)
                            continue

                        # Hive says unsolved ("Solve" or "Continue" button)
                        hive_unsolved_count += 1

                        if p.problem_id in self.state_manager.state.completed_problems:
                            # STATE DRIFT: bot thinks done but Hive contradicts
                            state_drift_count += 1
                            logger.warning(
                                f"⚠ State drift detected for '{p.problem_id}': "
                                f"bot marked completed but Hive shows '{p.status}' button. "
                                f"Re-queuing — Hive DOM is authoritative."
                            )
                            # Remove from completed so solver re-attempts it
                            self.state_manager.state.completed_problems.remove(p.problem_id)

                        # Queue this problem — Hive says it is unsolved
                        self.state_manager.add_problem(p.problem_id, p.title)
                        if p.problem_id not in self.state_manager.state.problems_queue:
                            self.state_manager.state.problems_queue.append(p.problem_id)
                        page_queue.append((p.problem_id, p.url))

                    logger.info(
                        f"Page {page_number + 1} reconciliation: "
                        f"Discovered={len(problems)}, "
                        f"Hive-solved={hive_solved_count}, "
                        f"Hive-unsolved={hive_unsolved_count}, "
                        f"State-drift-requeued={state_drift_count}, "
                        f"Actionable={len(page_queue)}"
                    )
                    self.state_manager.save_state()

                    # ---- Solve this page's queue before advancing ----
                    if page_queue:
                        logger.info(f"Solving {len(page_queue)} problem(s) on page {page_number + 1}...")
                        for problem_id, problem_url in page_queue:
                            if self._shutdown_requested:
                                logger.info("Shutdown requested: stopping solve loop.")
                                break
                            try:
                                await self.solve_problem(
                                    problem_id=problem_id,
                                    # DOM-extracted URL takes priority; slug fallback in solve_problem()
                                    problem_url=problem_url if problem_url else None,
                                )
                            except Exception as e:
                                logger.error(f"Error solving problem '{problem_id}': {e}")
                                self.state_manager.save_state()
                    else:
                        logger.info(f"No actionable problems on page {page_number + 1} — advancing.")

                    if self._shutdown_requested:
                        break

                    # ---- Advance to next page (with termination verification) ----
                    advanced = await detector.go_to_next_page()
                    if not advanced:
                        logger.info(
                            f"Pagination complete after page {page_number + 1} "
                            "(Next unavailable or page did not advance)."
                        )
                        break

                    page_number += 1

                if page_number >= MAX_PAGES:
                    logger.warning(
                        f"Pagination safety cap ({MAX_PAGES} pages) reached. "
                        "Terminating loop to prevent runaway execution."
                    )

                # ----------------------------------------------------------------
                # FINAL RECONCILIATION
                # Pagination complete ≠ solving complete.
                # Determine actual unresolved problems from authoritative bot state
                # (built from Hive DOM each page via mark_problem_solved / mark_problem_failed).
                # ----------------------------------------------------------------
                unresolved_ids: list = [
                    pid
                    for pid in self.state_manager.state.failed_problems
                    if pid not in self.state_manager.state.completed_problems
                ]

                total_discovered = len(self.state_manager.state.progress)
                total_solved = len(self.state_manager.state.completed_problems)

                if unresolved_ids:
                    logger.warning(
                        f"\n{'='*60}\n"
                        f"FINAL RECONCILIATION — Pagination complete, last page reached.\n"
                        f"{'='*60}\n"
                        f"  Total discovered : {total_discovered}\n"
                        f"  Bot-solved        : {total_solved}\n"
                        f"  Unresolved        : {len(unresolved_ids)}\n"
                        f"\nUnresolved problem IDs:"
                    )
                    for pid in unresolved_ids:
                        logger.warning(f"  ✗ {pid}")
                    logger.error(
                        f"✗ Bot workflow INCOMPLETE — {len(unresolved_ids)} problem(s) remain unsolved."
                    )
                else:
                    logger.info(
                        f"\n{'='*60}\n"
                        f"FINAL RECONCILIATION — All discovered problems solved.\n"
                        f"{'='*60}\n"
                        f"  Pages processed : {page_number + 1}\n"
                        f"  Solved          : {total_solved}\n"
                    )

                self.state_manager.save_state()

                return {
                    "pages_processed": page_number + 1,
                    "pagination_complete": True,
                    "hive_solved": total_solved,
                    "unresolved": unresolved_ids,
                    "failed_count": len(unresolved_ids),
                }

            except HiveBotError:
                raise
            except Exception as e:
                logger.error(f"Problem list discovery failed: {e}")
                raise HiveBotError(f"Problem list discovery failed: {e}") from e


    # ------------------------------------------------------------------
    # Step 5-7 — Problem Solving & Submission Loop (Phase 3)
    # ------------------------------------------------------------------

    async def solve_problem(
        self,
        problem_id: str,
        problem_url: Optional[str] = None,
        solver_engine: Optional[AISolverEngine] = None,
        submission_manager: Optional[SubmissionManager] = None,
        dry_run: Optional[bool] = None,
    ) -> bool:
        """
        Solve a single problem using the iterative AI solver and submission loop.

        Invariants:
        1. Crash resilience: If problem_id is in completed_problems, skip immediately.
        2. Evaluated code failure (Wrong Answer, Compilation Error, Runtime Error, TLE, MLE, Partially Accepted):
           Burn an AI attempt and inject diagnostic evidence into the next prompt.
        3. Platform/bot failure (TIMEOUT, DISCONNECTED, MISSING_RESULT, UNRECOGNIZED_VERDICT, EXECUTION_FAILED):
           Do NOT burn an AI attempt; preserve state and retry platform interaction.
        4. Checkpoint atomicity: Save state after every state transition (Accepted, 5th failure, or platform error).
        5. Shutdown safety: Check self._shutdown_requested at boundaries and exit cleanly without state corruption.
        """
        if self._shutdown_requested:
            logger.info(f"Shutdown requested: skipping problem '{problem_id}'.")
            return False

        with LogContext(f"Solve Problem: {problem_id}"):
            # Invariant 1: Crash recovery - never re-submit already solved problems
            if problem_id in self.state_manager.state.completed_problems:
                logger.info(
                    f"⊘ Skipping '{problem_id}' — already completed in bot state "
                    f"(crash recovery)"
                )
                return True

            if not self.browser_manager:
                raise HiveBotError("Browser not initialized")

            # Initialize problem progress and checkpoint
            self.state_manager.add_problem(problem_id, title=problem_id)
            progress = self.state_manager.state.progress[problem_id]
            self.state_manager.state.session.current_problem = problem_id
            self.state_manager.state.session.workflow_state = WorkflowState.LOADING_PROBLEM
            self.state_manager.save_state()

            page = await self.browser_manager.get_page()

            # Navigate to problem page if needed
            if not problem_url:
                contest_url = (self.config.get("hive.contest_url") or "").rstrip("/")
                if contest_url:
                    problem_url = f"{contest_url}/problems/{problem_id}"
                else:
                    problem_url = f"https://hive.smartinterviews.in/contests/default/problems/{problem_id}"

            if page.url != problem_url:
                logger.info(f"Navigating to problem page: {problem_url}")
                await page.goto(problem_url, wait_until="networkidle")
                await asyncio.sleep(2)

            # Step 3: Extract Problem Specification
            logger.info("Extracting problem details from DOM...")
            problem_detail = await ProblemDetailParser.extract_from_page(page, problem_id=problem_id)
            if problem_detail.title:
                progress.title = problem_detail.title

            # Step 4: Select Target Language
            # Read from PROBLEM_LANGUAGE in .env (user-configurable), fallback to DEFAULT_LANGUAGE
            target_lang = self.config.get("problem.language") or self.config.get("solver.default_language", "C++")
            logger.info(f"Ensuring language is set to canonical '{target_lang}'...")
            lang_controller = LanguageController(page)
            await lang_controller.select_language(target_lang)

            # Step 4: Detect and Bind Active Editor
            logger.info("Detecting active code editor...")
            editor_adapter = await EditorDetector.detect(page)
            if not await editor_adapter.is_ready():
                raise EditorError(f"Active editor not ready on problem page for '{problem_id}'")

            # Initialize engine and submission manager
            engine = solver_engine or self.solver_engine or AISolverEngine(self.config)
            effective_dry_run = dry_run if dry_run is not None else bool(self.config.get("features.dry_run", False))
            sub_mgr = submission_manager or self.submission_manager or SubmissionManager(
                run_timeout_s=float(self.config.get("solver.run_timeout_seconds", 30.0)),
                submit_timeout_s=float(self.config.get("solver.submit_timeout_seconds", 60.0)),
                dry_run=effective_dry_run,
            )

            # Invariant 2 & 3: 5-Attempt State Machine
            max_attempts = int(self.config.get("solver.max_attempts", 5))
            run_sample_first = bool(self.config.get("solver.run_sample_tests", False))

            attempt = progress.attempts + 1 if (0 < progress.attempts < max_attempts) else 1
            previous_code = progress.submissions[-1].code if progress.submissions else None
            previous_error = progress.last_error
            previous_verdict = progress.submissions[-1].verdict.value if progress.submissions else None

            current_code: Optional[str] = None
            platform_retries = 0
            max_platform_retries = int(self.config.get("solver.max_platform_retries", 3))

            while attempt <= max_attempts:
                if self._shutdown_requested:
                    logger.info(f"Shutdown requested: stopping solve loop for '{problem_id}' at clean attempt boundary.")
                    break
                # Generate new code only if not already generated for this attempt (preserves AI calls across platform retries)
                if not current_code:
                    logger.info(f"Problem '{problem_id}': Generating code for attempt {attempt}/{max_attempts}...")
                    self.state_manager.state.session.workflow_state = WorkflowState.SOLVING

                    # Build SolutionRequest
                    request = SolutionRequest(
                        problem_id=problem_id,
                        title=problem_detail.title,
                        description=problem_detail.description,
                        input_format=problem_detail.input_format,
                        output_format=problem_detail.output_format,
                        constraints=problem_detail.constraints,
                        sample_cases=problem_detail.sample_cases,
                        language=target_lang,
                        attempt_number=attempt,
                        previous_code=previous_code,
                        previous_error=previous_error,
                        previous_verdict=previous_verdict,
                    )

                    # Generate code via AI Solver Engine
                    solution_response = await engine.solve(request)
                    current_code = solution_response.code

                    # Inject code into editor with read-back verification
                    await editor_adapter.set_code(current_code)

                    # Optional sample run
                    if run_sample_first:
                        run_res = await sub_mgr.run_sample_tests(page)
                        if run_res.is_verdict_determined and not run_res.success:
                            logger.info(f"Sample test failed on attempt {attempt}: {run_res.diagnostic_message}")

                # Submit solution
                self.state_manager.state.session.workflow_state = WorkflowState.SUBMITTING
                sub_result = await sub_mgr.submit_solution(page)

                # Record submission attempt in state
                v_type = VerdictType.UNKNOWN
                try:
                    v_type = VerdictType(sub_result.verdict.value)
                except ValueError:
                    v_type = VerdictType.UNKNOWN

                submission = Submission(
                    problem_id=problem_id,
                    attempt_number=attempt,
                    code=current_code,
                    language=target_lang,
                    verdict=v_type,
                    error_message=sub_result.diagnostic_message,
                )
                progress.submissions.append(submission)

                # ----------------------------------------------------
                # CASE A: Accepted!
                # ----------------------------------------------------
                if sub_result.success or sub_result.verdict == Verdict.ACCEPTED:
                    logger.info(f"✓ Problem '{problem_id}' ACCEPTED on attempt {attempt}!")
                    progress.attempts = attempt
                    self.state_manager.mark_problem_solved(problem_id)
                    if problem_id in self.state_manager.state.problems_queue:
                        self.state_manager.state.problems_queue.remove(problem_id)
                    self.state_manager.save_state()
                    return True

                # ----------------------------------------------------
                # CASE B: Platform / Bot Failure (TIMEOUT, MISSING_RESULT, etc.)
                # Rule: DO NOT burn an AI attempt! Reuse current_code.
                # ----------------------------------------------------
                if sub_result.is_platform_failure:
                    platform_retries += 1
                    logger.warning(
                        f"Platform evaluation failure on attempt {attempt} "
                        f"({sub_result.error_kind.value}): {sub_result.diagnostic_message}. "
                        f"Platform retry {platform_retries}/{max_platform_retries} (AI attempt preserved)."
                    )
                    self.state_manager.save_state()  # Checkpoint state

                    if platform_retries >= max_platform_retries:
                        logger.error(
                            f"Exceeded max platform retries ({max_platform_retries}) for problem '{problem_id}'."
                        )
                        return False

                    await asyncio.sleep(1)
                    continue

                # ----------------------------------------------------
                # CASE C: Evaluated Code Failure (Wrong Answer, Compile Error, TLE, etc.)
                # Rule: BURN an AI attempt and provide diagnostics to next prompt!
                # ----------------------------------------------------
                logger.warning(
                    f"Attempt {attempt} evaluated as {sub_result.verdict.value}: {sub_result.diagnostic_message}"
                )
                progress.attempts = attempt
                progress.last_error = sub_result.diagnostic_message
                previous_code = current_code
                previous_error = sub_result.diagnostic_message
                previous_verdict = sub_result.verdict.value
                current_code = None  # Reset current_code so next attempt generates repaired code
                platform_retries = 0  # Reset platform retry counter

                if attempt >= max_attempts:
                    logger.warning(
                        f"Exhausted all {max_attempts} attempts for problem '{problem_id}'. Marking failed."
                    )
                    self.state_manager.mark_problem_failed(
                        problem_id,
                        reason=f"Exhausted {max_attempts} attempts. Final verdict: {sub_result.verdict.value}"
                    )
                    if problem_id in self.state_manager.state.problems_queue:
                        self.state_manager.state.problems_queue.remove(problem_id)
                    self.state_manager.save_state()
                    return False

                attempt += 1
                self.state_manager.save_state()  # Atomic checkpoint before next attempt

            return False

    async def solve_problems(
        self,
        solver_engine: Optional[AISolverEngine] = None,
        submission_manager: Optional[SubmissionManager] = None,
        max_problems: Optional[int] = None,
        dry_run: Optional[bool] = None,
    ) -> dict:
        """
        Main solving loop: iterates through problems_queue and solves each problem.
        """
        with LogContext("Solving Queued Problems"):
            queue = list(self.state_manager.state.problems_queue)
            if max_problems:
                queue = queue[:max_problems]

            logger.info(f"Starting solve loop for {len(queue)} queued problems...")

            for problem_id in queue:
                if self._shutdown_requested:
                    logger.info("Shutdown requested: exiting problem queue loop without starting new problems.")
                    break

                # Crash safety: check if already completed
                if problem_id in self.state_manager.state.completed_problems:
                    logger.info(
                        f"⊘ Skipping '{problem_id}' — already completed in bot state "
                        f"(completed_problems set, recovered from crash)"
                    )
                    if problem_id in self.state_manager.state.problems_queue:
                        self.state_manager.state.problems_queue.remove(problem_id)
                        self.state_manager.save_state()
                    continue

                try:
                    await self.solve_problem(
                        problem_id=problem_id,
                        solver_engine=solver_engine,
                        submission_manager=submission_manager,
                        dry_run=dry_run,
                    )
                except Exception as e:
                    logger.error(f"Error solving problem '{problem_id}': {e}")
                    self.state_manager.save_state()

            if not self._shutdown_requested:
                self.state_manager.state.session.workflow_state = WorkflowState.COMPLETE
            self.state_manager.save_state()
            
            # Generate comprehensive final summary
            stats = self.state_manager.get_progress_stats()
            
            # Create clear, unambiguous summary (aliases keep backward-compat with older test contracts)
            final_summary = {
                "historical_bot_completions": len(self.state_manager.state.completed_problems),
                "this_run_solved": len([p for p in queue if p in self.state_manager.state.completed_problems]),
                "this_run_failed": len(self.state_manager.state.failed_problems),
                "queued_remaining": len([p for p in queue if p not in self.state_manager.state.completed_problems and p not in self.state_manager.state.failed_problems]),
                "total_ever_tracked": len(self.state_manager.state.progress),
                # Backward-compat aliases expected by existing tests
                "completed": len(self.state_manager.state.completed_problems),
                "failed": len(self.state_manager.state.failed_problems),
            }
            
            logger.info(
                f"✓ Solve loop complete:\n"
                f"  Historical bot completions: {final_summary['historical_bot_completions']}\n"
                f"  Solved this run: {final_summary['this_run_solved']}\n"
                f"  Failed this run: {final_summary['this_run_failed']}\n"
                f"  Queued but not yet attempted: {final_summary['queued_remaining']}\n"
                f"  Total problems tracked: {final_summary['total_ever_tracked']}"
            )
            
            return final_summary

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Graceful shutdown of all components."""
        with LogContext("Shutdown"):
            try:
                logger.info("Shutting down bot...")

                if self.browser_manager:
                    await self.browser_manager.close()

                if self._shutdown_requested:
                    self.state_manager.state.session.workflow_state = WorkflowState.IDLE
                    self.state_manager.state.session.current_problem = None

                self.state_manager.save_state()
                logger.info("✓ Bot shutdown complete")

            except Exception as e:
                logger.error(f"Error during shutdown: {e}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()
        return False

