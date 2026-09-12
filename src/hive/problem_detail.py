"""
Problem Detail Extractor for Hive Automation Bot.

Extracts problem specifications from Hive's problem detail page:
- Title
- Description / Problem Statement
- Input Format
- Output Format
- Constraints
- Sample Cases (Input, Output, Explanation)
- Source URL & Problem ID
"""

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from src.utils.errors import ProblemExtractionError
from src.utils.logging_config import get_logger
from src.hive.ui_constants import (
    PROBLEM_DETAIL_TITLE,
    PROBLEM_DETAIL_DESCRIPTION,
)

logger = get_logger(__name__)


@dataclass
class SampleTestCase:
    """Represents a sample test case with input, expected output, and optional explanation."""
    input_data: str
    output_data: str
    explanation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input": self.input_data,
            "output": self.output_data,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SampleTestCase":
        return cls(
            input_data=data.get("input", ""),
            output_data=data.get("output", ""),
            explanation=data.get("explanation"),
        )


@dataclass
class ProblemDetail:
    """Structured representation of an extracted Hive problem."""
    problem_id: str
    title: str
    description: str
    input_format: str
    output_format: str
    constraints: str
    sample_cases: List[SampleTestCase] = field(default_factory=list)
    raw_text: str = ""
    source_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "title": self.title,
            "description": self.description,
            "input_format": self.input_format,
            "output_format": self.output_format,
            "constraints": self.constraints,
            "sample_cases": [sc.to_dict() for sc in self.sample_cases],
            "raw_text": self.raw_text,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProblemDetail":
        return cls(
            problem_id=data.get("problem_id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            input_format=data.get("input_format", ""),
            output_format=data.get("output_format", ""),
            constraints=data.get("constraints", ""),
            sample_cases=[SampleTestCase.from_dict(sc) for sc in data.get("sample_cases", [])],
            raw_text=data.get("raw_text", ""),
            source_url=data.get("source_url", ""),
        )


class _HTMLToPlainText(HTMLParser):
    """Converts HTML markup into formatted plain text preserving newlines and superscripts."""

    def __init__(self):
        super().__init__()
        self.text_pieces = []
        self._in_sup = False

    def handle_starttag(self, tag: str, attrs):
        tag_lower = tag.lower()
        if tag_lower in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr"):
            self.text_pieces.append("\n")
        elif tag_lower == "br":
            self.text_pieces.append("\n")
        elif tag_lower == "sup":
            self._in_sup = True
            self.text_pieces.append("^")

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr"):
            self.text_pieces.append("\n")
        elif tag_lower == "sup":
            self._in_sup = False

    def handle_data(self, data: str):
        self.text_pieces.append(data)

    def get_text(self) -> str:
        raw = "".join(self.text_pieces)
        lines = [line.strip() for line in raw.split("\n")]
        cleaned = []
        last_empty = False
        for line in lines:
            if not line:
                if not last_empty:
                    cleaned.append("")
                    last_empty = True
            else:
                cleaned.append(line)
                last_empty = False
        return "\n".join(cleaned).strip()


class ProblemDetailParser:
    """Parses problem statements from HTML or live DOM into structured ProblemDetail objects."""

    @staticmethod
    def html_to_text(html_content: str) -> str:
        """Convert HTML snippet to clean text."""
        parser = _HTMLToPlainText()
        parser.feed(html_content)
        return parser.get_text()

    @classmethod
    def parse_html(
        cls,
        html_content: str,
        title: str = "",
        source_url: str = "",
        problem_id: Optional[str] = None
    ) -> ProblemDetail:
        """
        Parse raw HTML content from problem description into ProblemDetail.
        """
        plain_text = cls.html_to_text(html_content)
        return cls.parse_text(
            text=plain_text,
            title=title,
            source_url=source_url,
            problem_id=problem_id
        )

    @classmethod
    def parse_text(
        cls,
        text: str,
        title: str = "",
        source_url: str = "",
        problem_id: Optional[str] = None
    ) -> ProblemDetail:
        """
        Parse plain text containing problem sections into ProblemDetail.
        """
        if not title:
            title = "Untitled Problem"

        if not problem_id:
            if source_url:
                path = urlparse(source_url).path.rstrip("/")
                parts = path.split("/")
                problem_id = parts[-1] if parts else "problem"
            else:
                problem_id = re.sub(r"[^a-zA-Z0-9_-]", "-", title.lower()).strip("-")

        # Normalize line endings
        text = text.replace("\r\n", "\n")

        # Headings regex
        input_format_pattern = re.compile(r"^Input\s+Format\b", re.IGNORECASE | re.MULTILINE)
        output_format_pattern = re.compile(r"^Output\s+Format\b", re.IGNORECASE | re.MULTILINE)
        constraints_pattern = re.compile(r"^Constraints\b", re.IGNORECASE | re.MULTILINE)
        example_pattern = re.compile(r"^(?:Example|Sample(?:\s+Cases?)?)\b", re.IGNORECASE | re.MULTILINE)

        # Find section offsets
        matches = [
            ("input_format", input_format_pattern.search(text)),
            ("output_format", output_format_pattern.search(text)),
            ("constraints", constraints_pattern.search(text)),
            ("example", example_pattern.search(text)),
        ]
        # Filter valid matches and sort by position
        valid_matches = [(name, m) for name, m in matches if m is not None]
        valid_matches.sort(key=lambda x: x[1].start())

        sections: Dict[str, str] = {
            "description": "",
            "input_format": "",
            "output_format": "",
            "constraints": "",
            "example": ""
        }

        if not valid_matches:
            # Fallback: entire text is description
            sections["description"] = text.strip()
        else:
            # Description is everything before the first section
            sections["description"] = text[:valid_matches[0][1].start()].strip()

            for i, (name, match) in enumerate(valid_matches):
                start = match.end()
                if i + 1 < len(valid_matches):
                    end = valid_matches[i + 1][1].start()
                else:
                    end = len(text)
                sections[name] = text[start:end].strip()

        # Parse sample test cases from example section
        sample_cases = cls._parse_sample_cases(sections["example"])

        return ProblemDetail(
            problem_id=problem_id,
            title=title,
            description=sections["description"],
            input_format=sections["input_format"],
            output_format=sections["output_format"],
            constraints=sections["constraints"],
            sample_cases=sample_cases,
            raw_text=text,
            source_url=source_url,
        )

    @classmethod
    def _parse_sample_cases(cls, example_text: str) -> List[SampleTestCase]:
        """Extract sample cases (input, output, explanation) from example text."""
        if not example_text:
            return []

        sample_cases: List[SampleTestCase] = []

        # Find "Input" and "Output" markers
        pattern = re.compile(
            r"Input\s*\n(.*?)\nOutput\s*\n(.*?)(?=\n(?:Input|Explanation|\Z))",
            re.IGNORECASE | re.DOTALL
        )

        matches = list(pattern.finditer(example_text))
        if matches:
            for m in matches:
                inp = m.group(1).strip()
                out = m.group(2).strip()

                explanation = None
                exp_pattern = re.compile(
                    r"Explanation\s*\n(.*?)(?=\nInput|\Z)",
                    re.IGNORECASE | re.DOTALL
                )
                exp_match = exp_pattern.search(example_text[m.end():])
                if exp_match:
                    explanation = exp_match.group(1).strip()

                sample_cases.append(SampleTestCase(
                    input_data=inp,
                    output_data=out,
                    explanation=explanation
                ))
        else:
            lines = [l.strip() for l in example_text.splitlines() if l.strip()]
            current_tag = None
            inp_lines = []
            out_lines = []
            exp_lines = []
            for line in lines:
                if line.lower() == "input":
                    if inp_lines and out_lines:
                        sample_cases.append(SampleTestCase(
                            input_data="\n".join(inp_lines).strip(),
                            output_data="\n".join(out_lines).strip(),
                            explanation="\n".join(exp_lines).strip() if exp_lines else None
                        ))
                        inp_lines, out_lines, exp_lines = [], [], []
                    current_tag = "input"
                elif line.lower() == "output":
                    current_tag = "output"
                elif line.lower() == "explanation":
                    current_tag = "explanation"
                else:
                    if current_tag == "input":
                        inp_lines.append(line)
                    elif current_tag == "output":
                        out_lines.append(line)
                    elif current_tag == "explanation":
                        exp_lines.append(line)

            if inp_lines and out_lines:
                sample_cases.append(SampleTestCase(
                    input_data="\n".join(inp_lines).strip(),
                    output_data="\n".join(out_lines).strip(),
                    explanation="\n".join(exp_lines).strip() if exp_lines else None
                ))

        return sample_cases

    @classmethod
    async def extract_from_page(cls, page: Page, problem_id: Optional[str] = None) -> ProblemDetail:
        """
        Extract problem details directly from an active Playwright page.
        """
        try:
            desc_el = await page.wait_for_selector(PROBLEM_DETAIL_DESCRIPTION, timeout=10000)
            if not desc_el:
                raise ProblemExtractionError(f"Description container not found: {PROBLEM_DETAIL_DESCRIPTION}")
        except PlaywrightTimeoutError as e:
            raise ProblemExtractionError(f"Timed out waiting for problem detail container: {e}") from e

        title = ""
        for selector in PROBLEM_DETAIL_TITLE.split(","):
            sel = selector.strip()
            title_el = await page.query_selector(sel)
            if title_el:
                t = (await title_el.inner_text()).strip()
                t = re.sub(r"\bbookmark_border\b", "", t).strip()
                if t:
                    title = t
                    break

        if not title:
            title = (await page.title()).strip()

        html_content = await desc_el.inner_html()
        if not html_content.strip():
            raise ProblemExtractionError("Extracted problem description HTML is empty")

        source_url = page.url
        detail = cls.parse_html(
            html_content=html_content,
            title=title,
            source_url=source_url
        )
        if problem_id:
            detail.problem_id = problem_id

        logger.info(
            "Extracted problem detail",
            extra={
                "problem_id": detail.problem_id,
                "title": detail.title,
                "samples_count": len(detail.sample_cases)
            }
        )
        return detail
