import pytest
from unittest.mock import AsyncMock, MagicMock
from src.hive.problem_list import Problem, ProblemListDetector

def test_problem_dataclass():
    prob = Problem(
        problem_id="max-element-in-array",
        title="Max Element in Array",
        url="https://hive.smartinterviews.in/contests/basic/problems/max-element-in-array",
        score=20,
        solved=True,
        status="Accepted",
    )
    assert prob.problem_id == "max-element-in-array"
    assert prob.score == 20
    assert prob.solved is True
    d = prob.to_dict()
    assert d["status"] == "Accepted"
    assert d["title"] == "Max Element in Array"

@pytest.mark.asyncio
async def test_is_on_problem_list_page(mock_page):
    detector = ProblemListDetector(mock_page)

    mock_page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems?page=0&pageSize=10"
    assert await detector.is_on_problem_list_page() is True

    mock_page.url = "https://hive.smartinterviews.in/login"
    mock_page.title = AsyncMock(return_value="Login")
    mock_locator = MagicMock()
    mock_locator.count = AsyncMock(return_value=0)
    mock_page.locator = MagicMock(return_value=mock_locator)
    assert await detector.is_on_problem_list_page() is False

@pytest.mark.asyncio
async def test_fetch_problems_and_classification(mock_page):
    detector = ProblemListDetector(mock_page)

    mock_eval_data = [
        {
            "problem_id": "max-element-in-array",
            "title": "Max Element in Array",
            "url": "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems/max-element-in-array",
            "score": 20,
            "solved": True,
            "status": "Accepted"
        },
        {
            "problem_id": "reverse-array",
            "title": "Reverse Array",
            "url": "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems/reverse-array",
            "score": 20,
            "solved": False,
            "status": "Unsolved"
        }
    ]
    mock_page.evaluate = AsyncMock(return_value=mock_eval_data)

    problems = await detector.fetch_problems()
    assert len(problems) == 2
    assert problems[0].solved is True
    assert problems[0].status == "Accepted"
    assert problems[1].solved is False
    assert problems[1].status == "Unsolved"

    assert await detector.get_solved_count() == 1
    assert await detector.get_unsolved_count() == 1
    unsolved = await detector.get_unsolved_problems()
    assert len(unsolved) == 1
    assert unsolved[0].problem_id == "reverse-array"

@pytest.mark.asyncio
async def test_click_continue_contest(mock_page):
    detector = ProblemListDetector(mock_page)
    mock_page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic"

    btn_mock = AsyncMock()
    btn_mock.is_visible = AsyncMock(return_value=True)
    btn_mock.click = AsyncMock()

    continue_locator = MagicMock()
    continue_locator.count = AsyncMock(return_value=1)
    continue_locator.first = btn_mock

    empty_locator = MagicMock()
    empty_locator.count = AsyncMock(return_value=0)

    def locator_side_effect(selector):
        if "Continue Contest" in selector or "Start Contest" in selector:
            return continue_locator
        return empty_locator

    mock_page.locator = MagicMock(side_effect=locator_side_effect)
    mock_page.wait_for_url = AsyncMock()

    # Once clicked, URL transitions to /problems
    def change_url(*args, **kwargs):
        mock_page.url = "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems"
    btn_mock.click.side_effect = change_url

    res = await detector.click_continue_contest()
    assert res is True
    btn_mock.click.assert_awaited_once()
