"""
Hive platform interaction module.

Exports:
- DOMInspector: Safe DOM query utilities
- ProblemListDetector: Problem list detection and navigation
- Problem: Problem metadata dataclass
"""

from .dom_queries import DOMInspector
from .problem_list import ProblemListDetector, Problem
from .problem_detail import ProblemDetail, SampleTestCase, ProblemDetailParser
from .submission import (
    Verdict,
    ExecutionErrorKind,
    SampleCaseResult,
    RunResult,
    SubmissionResult,
    SubmissionParser,
    SubmissionManager,
)

__all__ = [
    "DOMInspector",
    "ProblemListDetector",
    "Problem",
    "ProblemDetail",
    "SampleTestCase",
    "ProblemDetailParser",
    "Verdict",
    "ExecutionErrorKind",
    "SampleCaseResult",
    "RunResult",
    "SubmissionResult",
    "SubmissionParser",
    "SubmissionManager",
]
