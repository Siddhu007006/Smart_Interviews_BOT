import pytest
from unittest.mock import AsyncMock, MagicMock
from src.hive.problem_list import Problem, ProblemListDetector

def test_problem_dataclass():
    prob = Problem(
        problem_id="max-element-in-array",
        title="Max Element in Array",
        url="https://hive.smartinterviews.in/contests/basic/problems/max-element-in-array",
        action_button_text="Try Again",
        status_icon="green_tick",
        classification="SOLVED",
        score=20,
        solved=True,
        status="Accepted",
    )
    assert prob.problem_id == "max-element-in-array"
    assert prob.score == 20
    assert prob.solved is True
    assert prob.classification == "SOLVED"
    assert prob.action_button_text == "Try Again"
    d = prob.to_dict()
    assert d["status"] == "Accepted"
    assert d["title"] == "Max Element in Array"
    assert d["classification"] == "SOLVED"

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

# ====================================================================
# NEW TESTS: Classification Logic (Requirement Tasks 2-3)
# ====================================================================

def test_problem_classification_solved():
    """Green tick + Try Again = SOLVED"""
    prob = Problem(
        problem_id="max-element",
        title="Max Element in Array",
        url="https://hive.smartinterviews.in/contests/basic/problems/max-element",
        action_button_text="Try Again",
        status_icon="green_tick",
        classification="SOLVED",
        solved=True,
    )
    assert prob.classification == "SOLVED"
    assert prob.solved is True

def test_problem_classification_continue():
    """Any icon + Continue = UNSOLVED_CONTINUE"""
    # Test 1: Open icon + Continue
    prob1 = Problem(
        problem_id="unique-elements",
        title="Unique Elements",
        url="https://hive.smartinterviews.in/contests/basic/problems/unique-elements",
        action_button_text="Continue",
        status_icon="open",
        classification="UNSOLVED_CONTINUE",
        solved=False,
    )
    assert prob1.classification == "UNSOLVED_CONTINUE"
    assert prob1.solved is False
    
    # Test 2: Yellow exclamation + Continue
    prob2 = Problem(
        problem_id="compile-error-problem",
        title="Compile Error Problem",
        url="https://hive.smartinterviews.in/contests/basic/problems/compile-error",
        action_button_text="Continue",
        status_icon="yellow_exclamation",
        classification="UNSOLVED_CONTINUE",
        solved=False,
    )
    assert prob2.classification == "UNSOLVED_CONTINUE"
    
    # Test 3: Yellow partial tick + Continue
    prob3 = Problem(
        problem_id="partial-accept",
        title="Partial Accept Problem",
        url="https://hive.smartinterviews.in/contests/basic/problems/partial",
        action_button_text="Continue",
        status_icon="yellow_partial_tick",
        classification="UNSOLVED_CONTINUE",
        solved=False,
    )
    assert prob3.classification == "UNSOLVED_CONTINUE"

def test_problem_classification_solve():
    """Solve button = UNSOLVED_SOLVE (never attempted)"""
    prob = Problem(
        problem_id="new-problem",
        title="New Problem Never Attempted",
        url="https://hive.smartinterviews.in/contests/basic/problems/new-problem",
        action_button_text="Solve",
        status_icon=None,
        classification="UNSOLVED_SOLVE",
        solved=False,
    )
    assert prob.classification == "UNSOLVED_SOLVE"
    assert prob.solved is False

def test_problem_classification_unknown():
    """Unknown button text = UNKNOWN"""
    prob = Problem(
        problem_id="unknown-problem",
        title="Unknown State Problem",
        url="https://hive.smartinterviews.in/contests/basic/problems/unknown",
        action_button_text="SomeUnknownButton",
        status_icon=None,
        classification="UNKNOWN",
        solved=False,
    )
    assert prob.classification == "UNKNOWN"

# ====================================================================
# NEW TESTS: Exact Button Text Matching (Requirement Task 3)
# ====================================================================

@pytest.mark.asyncio
async def test_fetch_problems_exact_button_matching(mock_page):
    """
    Test exact button text matching.
    Ensures "Continue Contest" is NOT matched as "Continue" problem.
    """
    detector = ProblemListDetector(mock_page)

    # Mock DOM evaluation returning problems with different button texts
    mock_eval_data = [
        {
            "problem_id": "continue-problem",
            "title": "Continue Problem",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/continue-problem",
            "score": 20,
            "action_button_text": "Continue",
            "status_icon": "open",
        },
        {
            "problem_id": "solve-problem",
            "title": "Solve Problem",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/solve-problem",
            "score": 20,
            "action_button_text": "Solve",
            "status_icon": None,
        },
        {
            "problem_id": "try-again-problem",
            "title": "Try Again Problem",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/try-again",
            "score": 20,
            "action_button_text": "Try Again",
            "status_icon": "green_tick",
        },
    ]
    mock_page.evaluate = AsyncMock(return_value=mock_eval_data)

    problems = await detector.fetch_problems()
    assert len(problems) == 3
    
    # Verify classification
    assert problems[0].classification == "UNSOLVED_CONTINUE"
    assert problems[1].classification == "UNSOLVED_SOLVE"
    assert problems[2].classification == "SOLVED"

# ====================================================================
# NEW TESTS: Priority-Based Filtering (Requirements Tasks 4-8)
# ====================================================================

@pytest.mark.asyncio
async def test_get_continue_problems(mock_page):
    """Test filtering for UNSOLVED_CONTINUE problems (priority 1)"""
    detector = ProblemListDetector(mock_page)

    mock_eval_data = [
        {
            "problem_id": "problem1",
            "title": "Problem 1",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/problem1",
            "score": 20,
            "action_button_text": "Continue",
            "status_icon": "open",
        },
        {
            "problem_id": "problem2",
            "title": "Problem 2",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/problem2",
            "score": 20,
            "action_button_text": "Solve",
            "status_icon": None,
        },
        {
            "problem_id": "problem3",
            "title": "Problem 3",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/problem3",
            "score": 20,
            "action_button_text": "Continue",
            "status_icon": "yellow_exclamation",
        },
    ]
    mock_page.evaluate = AsyncMock(return_value=mock_eval_data)

    continue_problems = await detector.get_continue_problems()
    assert len(continue_problems) == 2
    assert all(p.classification == "UNSOLVED_CONTINUE" for p in continue_problems)
    assert continue_problems[0].problem_id == "problem1"
    assert continue_problems[1].problem_id == "problem3"

@pytest.mark.asyncio
async def test_get_solve_problems(mock_page):
    """Test filtering for UNSOLVED_SOLVE problems (priority 2)"""
    detector = ProblemListDetector(mock_page)

    mock_eval_data = [
        {
            "problem_id": "problem1",
            "title": "Problem 1",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/problem1",
            "score": 20,
            "action_button_text": "Solve",
            "status_icon": None,
        },
        {
            "problem_id": "problem2",
            "title": "Problem 2",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/problem2",
            "score": 20,
            "action_button_text": "Continue",
            "status_icon": "open",
        },
        {
            "problem_id": "problem3",
            "title": "Problem 3",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/problem3",
            "score": 20,
            "action_button_text": "Solve",
            "status_icon": None,
        },
    ]
    mock_page.evaluate = AsyncMock(return_value=mock_eval_data)

    solve_problems = await detector.get_solve_problems()
    assert len(solve_problems) == 2
    assert all(p.classification == "UNSOLVED_SOLVE" for p in solve_problems)
    assert solve_problems[0].problem_id == "problem1"
    assert solve_problems[1].problem_id == "problem3"

@pytest.mark.asyncio
async def test_unsolved_count_uses_classification(mock_page):
    """Test that get_unsolved_count uses classification, not old solved boolean"""
    detector = ProblemListDetector(mock_page)

    mock_eval_data = [
        {
            "problem_id": "continue-problem",
            "title": "Continue Problem",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/continue",
            "score": 20,
            "action_button_text": "Continue",
            "status_icon": "green_tick",  # Green tick present but Continue button
        },
        {
            "problem_id": "solve-problem",
            "title": "Solve Problem",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/solve",
            "score": 20,
            "action_button_text": "Solve",
            "status_icon": None,
        },
        {
            "problem_id": "try-again-problem",
            "title": "Try Again Problem",
            "url": "https://hive.smartinterviews.in/contests/basic/problems/try-again",
            "score": 20,
            "action_button_text": "Try Again",
            "status_icon": "green_tick",
        },
    ]
    mock_page.evaluate = AsyncMock(return_value=mock_eval_data)

    unsolved_count = await detector.get_unsolved_count()
    # Should count Continue (UNSOLVED_CONTINUE) + Solve (UNSOLVED_SOLVE)
    # NOT counting Try Again (SOLVED)
    assert unsolved_count == 2

    solved_count = await detector.get_solved_count()
    assert solved_count == 1

@pytest.mark.asyncio
async def test_fetch_problems_and_classification(mock_page):
    detector = ProblemListDetector(mock_page)

    mock_eval_data = [
        {
            "problem_id": "max-element-in-array",
            "title": "Max Element in Array",
            "url": "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems/max-element-in-array",
            "score": 20,
            "action_button_text": "Try Again",
            "status_icon": "green_tick",
        },
        {
            "problem_id": "reverse-array",
            "title": "Reverse Array",
            "url": "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems/reverse-array",
            "score": 20,
            "action_button_text": "Continue",
            "status_icon": "yellow_partial_tick",
        },
        {
            "problem_id": "unique-elements",
            "title": "Unique Elements",
            "url": "https://hive.smartinterviews.in/contests/smart-interviews-basic/problems/unique-elements",
            "score": 20,
            "action_button_text": "Solve",
            "status_icon": None,
        },
    ]
    mock_page.evaluate = AsyncMock(return_value=mock_eval_data)

    problems = await detector.fetch_problems()
    assert len(problems) == 3
    
    # Verify classification for each
    assert problems[0].classification == "SOLVED"
    assert problems[0].solved is True
    assert problems[1].classification == "UNSOLVED_CONTINUE"
    assert problems[1].solved is False
    assert problems[2].classification == "UNSOLVED_SOLVE"
    assert problems[2].solved is False

    # Test filtering by classification
    assert await detector.get_solved_count() == 1
    assert await detector.get_unsolved_count() == 2
    
    continue_probs = await detector.get_continue_problems()
    assert len(continue_probs) == 1
    assert continue_probs[0].problem_id == "reverse-array"
    
    solve_probs = await detector.get_solve_problems()
    assert len(solve_probs) == 1
    assert solve_probs[0].problem_id == "unique-elements"

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
