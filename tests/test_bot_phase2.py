import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from src.bot import HiveBot
from src.hive.problem_list import Problem
from src.utils.constants import WorkflowState

@pytest.fixture
def mock_bot(config_manager, temp_dir):
    bot = HiveBot(config_manager)
    bot.state_manager.state_file = temp_dir / "state.json"
    bot.browser_manager = AsyncMock()
    return bot

@pytest.mark.asyncio
async def test_detect_problem_list_already_on_page(mock_bot):
    page = AsyncMock()
    page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems"
    mock_bot.browser_manager.get_page = AsyncMock(return_value=page)

    mock_problems = [
        Problem(problem_id="p1", title="Problem 1", url="http://example.com/p1", solved=True, status="Accepted"),
        Problem(problem_id="p2", title="Problem 2", url="http://example.com/p2", solved=False, status="Unsolved"),
    ]

    with patch("src.bot.ProblemListDetector") as mock_detector_cls, \
         patch("src.bot.ExtensionChecker") as mock_checker_cls, \
         patch.object(mock_bot, "solve_problem", new_callable=AsyncMock) as mock_solve:
        detector = mock_detector_cls.return_value
        detector.is_on_problem_list_page = AsyncMock(return_value=True)
        detector.fetch_problems = AsyncMock(return_value=mock_problems)
        # No next page — terminate pagination loop after first page
        detector.go_to_next_page = AsyncMock(return_value=False)
        mock_solve.return_value = True

        await mock_bot._detect_problem_list()

        assert mock_bot.state_manager.state.session.workflow_state == WorkflowState.ON_PROBLEM_LIST
        assert "p1" in mock_bot.state_manager.state.completed_problems
        assert "p2" in mock_bot.state_manager.state.problems_queue
        assert mock_bot.state_manager.state.session.on_problem_list is True

@pytest.mark.asyncio
async def test_detect_problem_list_full_contest_navigation(mock_bot):
    page = AsyncMock()
    page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic"
    mock_bot.browser_manager.get_page = AsyncMock(return_value=page)
    mock_bot.config.config["hive"] = {"contest_url": "https://hive.smartinterviews.in/contests/smart-interviews-basic"}

    mock_problems = [
        Problem(problem_id="p-unsolved", title="Unsolved Problem", url="http://example.com/u", solved=False, status="Unsolved"),
    ]

    with patch("src.bot.ProblemListDetector") as mock_detector_cls, \
         patch("src.bot.ExtensionChecker") as mock_checker_cls, \
         patch.object(mock_bot, "solve_problem", new_callable=AsyncMock) as mock_solve:
        detector = mock_detector_cls.return_value
        detector.is_on_problem_list_page = AsyncMock(side_effect=[False, True])
        detector.navigate_to_contest = AsyncMock(return_value=True)
        detector.click_continue_contest = AsyncMock(return_value=True)
        detector.fetch_problems = AsyncMock(return_value=mock_problems)
        # No next page — terminate after page 1
        detector.go_to_next_page = AsyncMock(return_value=False)
        mock_solve.return_value = True

        checker = mock_checker_cls.return_value
        checker.verify_extension_ready = AsyncMock(return_value=True)

        await mock_bot._detect_problem_list()

        detector.navigate_to_contest.assert_awaited_once_with("https://hive.smartinterviews.in/contests/smart-interviews-basic")
        checker.verify_extension_ready.assert_awaited_once()
        detector.click_continue_contest.assert_awaited_once()
        assert "p-unsolved" in mock_bot.state_manager.state.problems_queue
