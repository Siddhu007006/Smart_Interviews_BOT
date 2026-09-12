import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from src.bot import HiveBot
from src.hive.problem_list import Problem
from src.utils.constants import WorkflowState

@pytest.fixture
def mock_bot(config_manager, temp_dir):
    bot = HiveBot(config_manager)
    # Use a temporary state file unique to this test to avoid conflicts
    import uuid
    bot.state_manager.state_file = temp_dir / f"state_{uuid.uuid4()}.json"
    bot.state_manager.state.problems_queue = []  # Reset queue
    bot.state_manager.state.completed_problems = []  # Reset completions
    bot.browser_manager = AsyncMock()
    return bot

@pytest.mark.asyncio
async def test_problem_classification_in_discovery(mock_bot):
    """Test that problems are correctly classified and queued during discovery"""
    page = AsyncMock()
    page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems"
    mock_bot.browser_manager.get_page = AsyncMock(return_value=page)

    mock_problems = [
        Problem(
            problem_id="solved_p1",
            title="Solved Problem 1",
            url="http://example.com/solved1",
            action_button_text="Try Again",
            status_icon="green_tick",
            classification="SOLVED",
            solved=True,
            status="Accepted"
        ),
        Problem(
            problem_id="continue_p1",
            title="Continue Problem 1",
            url="http://example.com/continue1",
            action_button_text="Continue",
            status_icon="open",
            classification="UNSOLVED_CONTINUE",
            solved=False,
            status="Unsolved"
        ),
        Problem(
            problem_id="solve_p1",
            title="Solve Problem 1",
            url="http://example.com/solve1",
            action_button_text="Solve",
            status_icon=None,
            classification="UNSOLVED_SOLVE",
            solved=False,
            status="Unsolved"
        ),
    ]

    with patch("src.bot.ProblemListDetector") as mock_detector_cls, \
         patch("src.bot.ExtensionChecker") as mock_checker_cls, \
         patch.object(mock_bot, "solve_problem", new_callable=AsyncMock) as mock_solve:
        detector = mock_detector_cls.return_value
        detector.is_on_problem_list_page = AsyncMock(return_value=True)
        detector.fetch_problems = AsyncMock(return_value=mock_problems)
        detector.go_to_next_page = AsyncMock(return_value=False)
        detector.navigate_to_contest = AsyncMock(return_value=True)
        mock_solve.return_value = True

        result = await mock_bot._detect_problem_list()

        # Verify discovery phase completed and correct classification
        assert mock_bot.state_manager.state.session.workflow_state == WorkflowState.ON_PROBLEM_LIST
        assert result["pages_processed"] == 1
        # Verify discovery found 1 solved, 1 continue, 1 solve in reconciliation
        assert result["reconciliation"]["reconciled_solved"] == 1
        assert result["reconciliation"]["reconciled_continue"] == 1
        assert result["reconciliation"]["reconciled_solve"] == 1

@pytest.mark.asyncio
async def test_dom_order_top_to_bottom(mock_bot):
    """Test that problems are solved in exact DOM top-to-bottom order.

    The old architecture prioritised Continue before Solve globally (across all pages),
    which caused page-8 Continue problems to be solved before page-1 Solve problems.

    The new architecture processes each page inline in DOM order — the order problems
    appear visually on screen, top to bottom.  No priority distinction is made between
    Solve and Continue buttons; position on the page is the only ordering criterion.
    """
    page = AsyncMock()
    page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems"
    mock_bot.browser_manager.get_page = AsyncMock(return_value=page)

    # DOM order: Solve → Continue → Solve  (mixed — bot must solve in this exact order)
    mock_problems = [
        Problem(
            problem_id="solve_first",
            title="Solve First",
            url="http://example.com/s1",
            action_button_text="Solve",
            status_icon=None,
            classification="UNSOLVED_SOLVE",
            solved=False,
        ),
        Problem(
            problem_id="continue_middle",
            title="Continue Middle",
            url="http://example.com/c1",
            action_button_text="Continue",
            status_icon="open",
            classification="UNSOLVED_CONTINUE",
            solved=False,
        ),
        Problem(
            problem_id="solve_last",
            title="Solve Last",
            url="http://example.com/s2",
            action_button_text="Solve",
            status_icon=None,
            classification="UNSOLVED_SOLVE",
            solved=False,
        ),
    ]

    solve_order = []

    async def track_solve(problem_id, **kwargs):
        solve_order.append(problem_id)
        return True

    with patch("src.bot.ProblemListDetector") as mock_detector_cls, \
         patch("src.bot.ExtensionChecker") as mock_checker_cls, \
         patch.object(mock_bot, "solve_problem", new_callable=AsyncMock, side_effect=track_solve):
        detector = mock_detector_cls.return_value
        detector.is_on_problem_list_page = AsyncMock(return_value=True)
        detector.fetch_problems = AsyncMock(return_value=mock_problems)
        detector.go_to_next_page = AsyncMock(return_value=False)
        detector.navigate_to_contest = AsyncMock(return_value=True)

        await mock_bot._detect_problem_list()

        # Must be solved in DOM order: solve_first → continue_middle → solve_last
        assert solve_order == ["solve_first", "continue_middle", "solve_last"], (
            f"Expected DOM order [solve_first, continue_middle, solve_last], got {solve_order}"
        )

