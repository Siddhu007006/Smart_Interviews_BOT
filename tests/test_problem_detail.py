"""
Unit tests for Problem Detail Extractor (Step 3).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.hive.problem_detail import ProblemDetail, SampleTestCase, ProblemDetailParser
from src.utils.errors import ProblemExtractionError


HIVE_EMPIRICAL_HTML = """
<p>Find the maximum element from the given array of integers.</p>
<p><br></p>
<p><strong>Input Format</strong></p>
<p>The first line of input contains N - the size of the array and the second line contains the elements of the array.</p>
<p><br></p>
<p><strong>Output Format</strong></p>
<p>Print the maximum element of the given array.</p>
<p><br></p>
<p><strong>Constraints</strong></p>
<p>1 &lt;= N &lt;= 10<sup>3</sup></p>
<p>-10<sup>9</sup> &lt;= ar[i] &lt;= 10<sup>9</sup></p>
<p><br></p>
<p><strong>Example</strong></p>
<p><strong>Input</strong></p>
<p>5<br>-2 -19 8 15 4</p>
<p><strong>Output</strong></p>
<p>15</p>
<p><strong>Explanation</strong></p>
<p>Self Explanatory</p>
"""


def test_parse_html_live_hive_snippet():
    """Verify parsing against actual Hive DOM HTML structure."""
    detail = ProblemDetailParser.parse_html(
        html_content=HIVE_EMPIRICAL_HTML,
        title="Max Element in Array",
        source_url="https://hive.smartinterviews.in/contests/smart-interviews-basic/problems/max-element-in-array"
    )

    assert detail.title == "Max Element in Array"
    assert detail.problem_id == "max-element-in-array"
    assert detail.description == "Find the maximum element from the given array of integers."
    assert "size of the array" in detail.input_format
    assert "maximum element" in detail.output_format
    assert "1 <= N <= 10^3" in detail.constraints
    assert "-10^9 <= ar[i] <= 10^9" in detail.constraints
    assert len(detail.sample_cases) == 1

    sample = detail.sample_cases[0]
    assert sample.input_data == "5\n-2 -19 8 15 4"
    assert sample.output_data == "15"
    assert sample.explanation == "Self Explanatory"


def test_parse_multiple_sample_cases():
    """Verify parsing multiple sample test cases."""
    text = """
Given two numbers, calculate their sum.

Input Format
First line contains T, number of test cases.
Next T lines contain two integers A and B.

Output Format
Print sum for each test case.

Constraints
1 <= T <= 100

Example
Input
2
1 2
3 4
Output
3
7
Explanation
1+2=3, 3+4=7
"""
    detail = ProblemDetailParser.parse_text(
        text=text,
        title="Sum of Two Numbers",
        source_url="https://hive.smartinterviews.in/contests/test/problems/sum-of-two"
    )

    assert detail.title == "Sum of Two Numbers"
    assert detail.problem_id == "sum-of-two"
    assert detail.description == "Given two numbers, calculate their sum."
    assert len(detail.sample_cases) == 1
    assert detail.sample_cases[0].input_data == "2\n1 2\n3 4"
    assert detail.sample_cases[0].output_data == "3\n7"
    assert detail.sample_cases[0].explanation == "1+2=3, 3+4=7"


def test_parse_unstructured_fallback():
    """Verify fallback behavior when problem has no formatted section headers."""
    raw_text = "Compute factorial of N modulo 10^9+7.\nInput is single integer N."
    detail = ProblemDetailParser.parse_text(raw_text, title="Factorial")

    assert detail.title == "Factorial"
    assert detail.description == raw_text
    assert detail.input_format == ""
    assert detail.output_format == ""
    assert detail.constraints == ""
    assert len(detail.sample_cases) == 0


def test_serialization_roundtrip():
    """Verify to_dict and from_dict roundtrip fidelity."""
    sample = SampleTestCase(input_data="1 2", output_data="3", explanation="add")
    original = ProblemDetail(
        problem_id="prob-1",
        title="Sample",
        description="Desc",
        input_format="InFmt",
        output_format="OutFmt",
        constraints="Const",
        sample_cases=[sample],
        raw_text="raw",
        source_url="http://hive/test"
    )

    data = original.to_dict()
    restored = ProblemDetail.from_dict(data)

    assert restored.problem_id == original.problem_id
    assert restored.title == original.title
    assert restored.description == original.description
    assert len(restored.sample_cases) == 1
    assert restored.sample_cases[0].input_data == "1 2"
    assert restored.sample_cases[0].explanation == "add"


@pytest.mark.asyncio
async def test_extract_from_page_missing_description_raises():
    """Verify extract_from_page raises ProblemExtractionError on timeout/missing selector."""
    page = MagicMock()
    page.wait_for_selector = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))

    with pytest.raises(ProblemExtractionError, match="Timed out waiting"):
        await ProblemDetailParser.extract_from_page(page)


@pytest.mark.asyncio
async def test_extract_from_page_empty_html_raises():
    """Verify extract_from_page raises ProblemExtractionError if HTML is empty."""
    page = MagicMock()
    desc_mock = MagicMock()
    desc_mock.inner_html = AsyncMock(return_value="   ")
    page.wait_for_selector = AsyncMock(return_value=desc_mock)
    page.query_selector = AsyncMock(return_value=None)
    page.title = AsyncMock(return_value="Some Title")
    page.url = "http://hive/problems/test"

    with pytest.raises(ProblemExtractionError, match="HTML is empty"):
        await ProblemDetailParser.extract_from_page(page)
